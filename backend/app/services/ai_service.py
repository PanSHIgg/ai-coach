"""AI 对话服务：次数配额 + RAG 检索 + LLM 生成 + 对话落库 + 降级免责。

真源 `docs/split/06-AI服务.md`：
- §2.3 系统提示词固定"AI 饮食教练"身份，只答体重管理、疾病引导就医；
- §2.4 AI 对话限流 20 次/分钟/用户；
- §4.3 返回结构 `{reply, intent, times_left, references}`；
- §4.4 次数用尽返 4001（"今日对话次数已用完，邀请好友可解锁更多"）；
- §六 所有 AI 输出带免责声明；服务不可用/超时降级预设 FAQ（6001），不卡死。

D-09：LLM 与 VLM 统一走 OpenAI 兼容协议（/v1/chat/completions），不再区分厂商适配器；
连接与模型信息使用时由 env 设置（LLM_*/VLM_* 三件套），未配置时明确降级（Mock/模板）。

日期口径：业务日界 UTC+8，与 `app/services/account.py` 一致。
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
import uuid
from datetime import UTC, date, datetime, time, timedelta, timezone
from typing import Any, NamedTuple

import httpx
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import LLMClient
from app.ai.mock import MockLLMClient
from app.ai.prompts import AI_COACH_SYSTEM_PROMPT, AI_DISCLAIMER, AI_UNAVAILABLE_FAQ
from app.core.config import Settings, get_settings
from app.core.errors import AppException
from app.core.logging import get_logger
from app.core.rate_limit import check_rate_limit
from app.models import AiDialog, AiKnowledge, DailySnapshot, UserBenefit, WeightRecord
from app.schemas.ai import WeeklyCommentData
from app.schemas.common import ErrorCode

logger = get_logger(__name__)

TZ = timezone(timedelta(hours=8))
TOP_K = 3  # RAG 取前 3 条
NO_TIMES_MESSAGE = "今日对话次数已用完，邀请好友可解锁更多"

# 各档每日 AI 对话配额（docs/changes/2026-10-01-邀请规则变更记录.md §二）：
# tier0 基础=10（与 AI_DAILY_TIMES 默认值一致）、1 人 tier1=20、3 人 tier2=40、
# 10 人 tier3=**-1 表示不限次**（永久终身版）。集中定义便于调整。
TIER_AI_QUOTA: dict[int, int] = {0: 10, 1: 20, 2: 40, 3: -1}


def ai_quota_for_tier(tier: int, daily: int) -> int:
    """按 tier 取每日 AI 对话配额；-1=不限次；tier0 用配置 `AI_DAILY_TIMES`（默认 10）。"""
    tier = int(tier)
    if tier <= 0:
        return int(daily)
    return TIER_AI_QUOTA.get(tier, int(daily))


# 轻量规则分类（不再二次调用 LLM）；疾病类置顶，避免被"饿/油"抢先命中
_INTENT_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("病", "疼", "药", "诊断", "就医"), "medical_redirect"),
    (("饿", "能吃什么", "还吃", "加餐"), "hunger_rescue"),
    (("油", "热量", "卡路里", "脂肪", "碳水"), "calorie_query"),
)
_DEFAULT_INTENT = "general"

_TOKEN_SPLIT = re.compile(r"[^\w一-鿿]+")


class ChatResult(NamedTuple):
    """对话结果：`(reply, intent, times_left, references)`。"""

    reply: str
    intent: str
    times_left: int
    references: list[str]


def classify_intent(message: str) -> str:
    """关键词规则分类；无命中一律 general。"""
    for keywords, intent in _INTENT_RULES:
        if any(k in message for k in keywords):
            return intent
    return _DEFAULT_INTENT


def _terms(query: str, max_terms: int = 8) -> list[str]:
    """切词：按非词字符切段，段长 > 2 时取 2 字滑窗（中文无空格，滑窗用于 ILIKE 兜底）。"""
    terms: list[str] = []
    for run in _TOKEN_SPLIT.split(query):
        if not run:
            continue
        if len(run) <= 2:
            terms.append(run)
        else:
            terms.extend(run[i : i + 2] for i in range(len(run) - 1))
    return list(dict.fromkeys(terms))[:max_terms]


def _escape_like(value: str) -> str:
    """转义 LIKE 通配符：提问里的 % / _ 不当通配符用（搭配 ilike(escape="\\")）。"""
    for old, new in (("\\", "\\\\"), ("%", "\\%"), ("_", "\\_")):
        value = value.replace(old, new)
    return value


async def retrieve_knowledge(
    session: AsyncSession, query: str, limit: int = TOP_K
) -> list[AiKnowledge]:
    """RAG 检索 top-K：pg_trgm 中文可用检索（ILIKE 命中 + similarity 排序）。

    弃用 `to_tsvector('simple')`（不切中文，长句/子串会漏召回）；改以完整问句 + 2 字滑窗
    切词做 ILIKE 召回（GIN trgm 索引可加速 food/food_alias；知识库无索引亦正确），
    再按 title/content 的 `similarity()` 排序取 top-K。检索异常按无引用继续，不中断对话。
    """
    kw = (query or "").strip()
    if not kw:
        return []
    terms = list(dict.fromkeys([kw, *_terms(kw)]))
    match_any = or_(
        *[
            column.ilike(f"%{_escape_like(t)}%", escape="\\")
            for t in terms
            for column in (AiKnowledge.content, AiKnowledge.title)
        ]
    )
    score = func.greatest(
        func.similarity(AiKnowledge.title, kw),
        func.similarity(AiKnowledge.content, kw),
    )
    try:
        rows = (
            (
                await session.execute(
                    select(AiKnowledge)
                    .where(match_any)
                    .order_by(score.desc(), AiKnowledge.id)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return list(rows)
    except Exception:  # noqa: BLE001 - 检索异常须降级，不得中断对话
        logger.warning("知识库 pg_trgm 检索失败，本次无引用")
        return []


def _build_messages(message: str, docs: list[AiKnowledge]) -> list[dict]:
    """系统提示词 + RAG 上下文 + 用户提问（OpenAI messages 格式）。"""
    messages: list[dict] = [{"role": "system", "content": AI_COACH_SYSTEM_PROMPT}]
    if docs:
        context = "\n".join(f"- {d.title or ''}: {d.content}" for d in docs)
        messages.append({"role": "system", "content": f"可参考下列知识库内容回答：\n{context}"})
    messages.append({"role": "user", "content": message})
    return messages


# ---------------------------------------------------------------------------
# D-09：OpenAI 兼容单一客户端（LLM 与 VLM 共用，POST {base_url}/chat/completions）
# ---------------------------------------------------------------------------

# 视觉识别提示词：要求纯 JSON 输出，便于后端解析并匹配 food 表
_VISION_PROMPT = (
    "你是食物识别助手。识别图片中的食物，只输出 JSON，不要任何解释文字，格式：\n"
    '{"items":[{"name":"食物中文名","confidence":0.0-1.0,"portion_g":整数克重,'
    '"kcal_100g":每100克热量整数}]}\n'
    "最多 5 项，按画面占比从大到小排序。"
)

_JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL)


def _extract_json(text: str) -> Any:
    """从模型输出中抠出 JSON：优先 ```json 代码块，其次首尾括号之间的片段。"""
    text = (text or "").strip()
    m = _JSON_BLOCK.search(text)
    if m:
        return json.loads(m.group(1))
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        start, end = text.find("["), text.rfind("]")
    if start == -1 or end <= start:
        raise ValueError(f"模型未返回 JSON：{text[:200]}")
    return json.loads(text[start : end + 1])


def _openai_compatible_chat(
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict],
    *,
    timeout: float,
    temperature: float = 0.5,
    max_tokens: int = 1024,
) -> str:
    """OpenAI 兼容对话客户端（同步 httpx，调用方放线程池）：标准请求/响应结构。

    POST `{base_url}/chat/completions`，payload 为 model/messages/temperature/max_tokens，
    取 `choices[0].message.content`。任何异常由调用方捕获并降级（6001/模板），不外泄。
    """
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    with httpx.Client(timeout=httpx.Timeout(timeout, connect=3.0)) as client:
        resp = client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
    return (data["choices"][0]["message"].get("content") or "").strip()


class _OpenAICompatLLM(LLMClient):
    """OpenAI 兼容对话客户端（LLM_* 三件套）；由 `llm_client_for` 按配置装配。"""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        timeout: float,
        temperature: float = 0.5,
        max_tokens: int = 1024,
    ):
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.temperature = temperature
        self.max_tokens = max_tokens

    def chat(self, messages: list[dict]) -> str:
        return _openai_compatible_chat(
            self.base_url,
            self.api_key,
            self.model,
            messages,
            timeout=self.timeout,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )


def llm_client_for(s: Settings) -> LLMClient:
    """按 env 装配 LLM 客户端：LLM_BASE_URL+LLM_API_KEY 齐备 → OpenAI 兼容；否则 Mock（明确降级）。"""
    if s.LLM_BASE_URL and s.LLM_API_KEY:
        return _OpenAICompatLLM(s.LLM_BASE_URL, s.LLM_API_KEY, s.LLM_MODEL, timeout=s.AI_TIMEOUT)
    logger.warning("[ai] LLM_BASE_URL/LLM_API_KEY 未配置，走 Mock 降级")
    return MockLLMClient()


def _vision_message(image: bytes | str) -> dict:
    """OpenAI vision 消息格式：content 数组含 image_url；bytes → base64 data URL，str → https URL。"""
    url = (
        f"data:image/jpeg;base64,{base64.b64encode(image).decode()}"
        if isinstance(image, bytes)
        else image
    )
    return {
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": url}},
            {"type": "text", "text": _VISION_PROMPT},
        ],
    }


class _OpenAICompatVLM:
    """OpenAI 兼容视觉客户端（VLM_* 三件套）：图片走 vision 消息，输出 JSON 候选列表。"""

    def __init__(self, base_url: str, api_key: str, model: str, *, timeout: float):
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def recognize_food(self, image_bytes: bytes) -> list[dict]:
        raw = _openai_compatible_chat(
            self.base_url,
            self.api_key,
            self.model,
            [_vision_message(image_bytes)],
            timeout=self.timeout,
        )
        parsed = _extract_json(raw)
        items = parsed.get("items") if isinstance(parsed, dict) else parsed
        return items if isinstance(items, list) else []


async def _invoke(client: LLMClient, messages: list[dict]) -> str:
    """兼容异步/同步客户端：`achat` 优先，否则同步 `chat` 放线程池。"""
    achat = getattr(client, "achat", None)
    if callable(achat):
        return await achat(messages)
    return await asyncio.to_thread(client.chat, messages)


async def generate_reply(client: LLMClient, messages: list[dict], *, timeout: float) -> str:
    """调 LLM 生成回复并追加免责声明；异常/超时 → 6001 + 预设 FAQ（不卡死）。"""
    try:
        text = await asyncio.wait_for(_invoke(client, messages), timeout=timeout)
    except TimeoutError as exc:
        logger.warning("AI 对话超时，降级 FAQ", extra={"timeout": timeout})
        raise AppException(ErrorCode.AI_UNAVAILABLE, AI_UNAVAILABLE_FAQ) from exc
    except Exception as exc:  # noqa: BLE001 - 任何 LLM 故障都按不可用降级
        logger.warning("AI 对话调用失败，降级 FAQ", extra={"reason": str(exc)})
        raise AppException(ErrorCode.AI_UNAVAILABLE, AI_UNAVAILABLE_FAQ) from exc
    reply = (text or "").strip()
    if AI_DISCLAIMER not in reply:
        reply = f"{reply}{AI_DISCLAIMER}" if reply else AI_DISCLAIMER
    return reply


async def ensure_benefit(
    session: AsyncSession, user_id: int, settings: Settings | None = None
) -> UserBenefit:
    """取次数行：不存在按 tier 配额初始化；`ai_times_reset_at` 早于今日 00:00 时按 tier 配额重置。

    每日重置基线**按 tier 取配额**（`ai_quota_for_tier`）：tier0=10、tier1=20、tier2=40；
    tier3=-1 不限次 → 无配额概念，跳过重置（与邀请绑定实时升档链路一致）。

    行锁：并发对话同时读到同一余额会扣减丢失（名额可被超用），故按 user_id 加 FOR UPDATE。

    事务边界：初始化/重置只 `flush()` 不 `commit()`——提前提交会释放 FOR UPDATE 行锁，
    并发请求各自读到同一重置后余额、分别扣 1 提交 → 丢失更新（名额超用）。
    必须让「加锁读 → 重置 → 扣减」落在 `chat()` 末尾的同一次 commit 内。
    """
    s = settings or get_settings()
    benefit = (
        await session.execute(
            select(UserBenefit).where(UserBenefit.user_id == user_id).with_for_update()
        )
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if benefit is None:
        benefit = UserBenefit(
            user_id=user_id,
            tier=0,
            ai_times_left=ai_quota_for_tier(0, s.AI_DAILY_TIMES),
            ai_times_reset_at=now,
        )
        session.add(benefit)
        await session.flush()  # 不提交：与 chat() 的扣减同事务，避免提前放锁
        return benefit
    quota = ai_quota_for_tier(int(benefit.tier), s.AI_DAILY_TIMES)
    if quota == -1:  # 不限次（tier3）：无每日配额概念，无需重置/扣减
        return benefit
    today_start = datetime.combine(datetime.now(TZ).date(), time.min, tzinfo=TZ)
    if benefit.ai_times_reset_at is None or benefit.ai_times_reset_at < today_start:
        benefit.ai_times_left = quota
        benefit.ai_times_reset_at = now
        await session.flush()  # 同上：重置与扣减必须原子
    return benefit


async def get_times_left(
    session: AsyncSession, user_id: int, settings: Settings | None = None
) -> int:
    """剩余对话次数（含 0 点重置）。"""
    benefit = await ensure_benefit(session, user_id, settings)
    return int(benefit.ai_times_left)


def _as_uuid(session_id: str | None) -> uuid.UUID | None:
    """会话 id → UUID；非 UUID 字符串（如前端占位 "s-1"）用 uuid5 稳定派生，避免落库类型错。"""
    if not session_id:
        return None
    try:
        return uuid.UUID(str(session_id))
    except ValueError:
        return uuid.uuid5(uuid.NAMESPACE_URL, str(session_id))


async def chat(
    session: AsyncSession,
    *,
    user_id: int,
    session_id: str | None,
    message: str,
    settings: Settings | None = None,
    llm_client: LLMClient | None = None,
) -> ChatResult:
    """一次 AI 对话：限流 → 次数校验 → RAG → LLM（失败 6001）→ 落 ai_dialog → 扣次数。"""
    s = settings or get_settings()
    if s.RATE_LIMIT_ENABLED and not await check_rate_limit(
        f"ai:chat:user:{user_id}", s.RATE_LIMIT_AI_PER_MIN, s.RATE_LIMIT_WINDOW_SECONDS
    ):
        raise AppException(ErrorCode.RATE_LIMITED)

    benefit = await ensure_benefit(session, user_id, s)
    # tier3=-1 不限次：不扣不拦（ai/times 响应字段类型 int 不变）
    if (
        ai_quota_for_tier(int(benefit.tier), s.AI_DAILY_TIMES) != -1
        and int(benefit.ai_times_left) <= 0
    ):
        raise AppException(ErrorCode.QUOTA_EXCEEDED, NO_TIMES_MESSAGE)

    intent = classify_intent(message)
    docs = await retrieve_knowledge(session, message)
    references = [f"knowledge:{d.id}" for d in docs]

    client = llm_client or llm_client_for(s)
    model = str(getattr(client, "model", "") or type(client).__name__)[:64]
    dialog_session_id = _as_uuid(session_id)
    reply = await generate_reply(client, _build_messages(message, docs), timeout=s.AI_TIMEOUT)

    session.add(
        AiDialog(
            user_id=user_id,
            session_id=dialog_session_id,
            role="user",
            content=message,
            intent=intent,
            model=model,
        )
    )
    session.add(
        AiDialog(
            user_id=user_id,
            session_id=dialog_session_id,
            role="assistant",
            content=reply,
            intent=intent,
            model=model,
        )
    )
    if ai_quota_for_tier(int(benefit.tier), s.AI_DAILY_TIMES) != -1:
        benefit.ai_times_left = max(0, int(benefit.ai_times_left) - 1)
    await session.commit()
    return ChatResult(reply, intent, int(benefit.ai_times_left), references)


# ---------------------------------------------------------------------------
# BE7c：AI 周点评（每周热量控制周报）
# ---------------------------------------------------------------------------


class WeekStats(NamedTuple):
    """周报聚合数据。"""

    key: str
    days: int
    intake: float
    deficit: float  # 负值为缺口
    steps: int
    weight_change: float | None


def _iso_week_key(d: date) -> str:
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


def _week_range(week: str | None) -> tuple[str, date, date]:
    """周号 → (key, monday, sunday)；缺省取本周（UTC+8）。"""
    if week:
        try:
            monday = datetime.strptime(f"{week}-1", "%G-W%V-%u").date()
        except ValueError as exc:
            raise AppException(ErrorCode.VALIDATION_ERROR, "周号格式应为 YYYY-Www") from exc
        return week, monday, monday + timedelta(days=6)
    today = datetime.now(TZ).date()
    monday = today - timedelta(days=today.weekday())
    return _iso_week_key(today), monday, monday + timedelta(days=6)


async def _collect_week_stats(
    session: AsyncSession, user_id: int, key: str, start: date, end: date
) -> WeekStats:
    rows = (
        (
            await session.execute(
                select(DailySnapshot).where(
                    DailySnapshot.user_id == user_id,
                    DailySnapshot.snapshot_date >= start,
                    DailySnapshot.snapshot_date <= end,
                )
            )
        )
        .scalars()
        .all()
    )
    intake = sum(float(r.intake or 0) for r in rows)
    deficit = sum(float(r.deficit or 0) for r in rows)
    steps = sum(int(r.steps or 0) for r in rows)
    weights = (
        (
            await session.execute(
                select(WeightRecord)
                .where(
                    WeightRecord.user_id == user_id,
                    WeightRecord.record_at >= start,
                    WeightRecord.record_at <= end,
                )
                .order_by(WeightRecord.record_at)
            )
        )
        .scalars()
        .all()
    )
    change = (
        round(float(weights[-1].weight) - float(weights[0].weight), 1)
        if len(weights) >= 2
        else None
    )
    return WeekStats(
        key=key,
        days=len(rows),
        intake=round(intake, 1),
        deficit=round(deficit, 1),
        steps=steps,
        weight_change=change,
    )


def _template_comment(stats: WeekStats) -> str:
    """无 Key 降级：基于真实聚合数据的确定性周点评模板。"""
    if stats.days == 0:
        return "本周还没有记录，先完成 1 天饮食打卡，我们下周一起看趋势。"
    total = abs(stats.deficit)
    trend = "保持不错" if stats.deficit <= 0 else "略有盈余"
    weight_part = (
        f"，体重变化 {stats.weight_change:+g}kg" if stats.weight_change is not None else ""
    )
    daily_steps = int(stats.steps / max(stats.days, 1))
    return (
        f"本周你记录了 {stats.days} 天，总摄入 {stats.intake:.0f} kcal，"
        f"热量缺口约 {total:.0f} kcal，{trend}，日均步数 {daily_steps} 步{weight_part}。"
        "建议继续保持规律三餐与足量饮水，下周争取多完成 1 天打卡。"
    )


async def weekly_comment(
    session: AsyncSession,
    *,
    user_id: int,
    week: str | None = None,
    settings: Settings | None = None,
    llm_client: LLMClient | None = None,
) -> WeeklyCommentData:
    """AI 周点评：聚合本周数据 → LLM 生成点评（无 Key 落 mock 模板）+ 免责声明。"""
    s = settings or get_settings()
    key, start, end = _week_range(week)
    stats = await _collect_week_stats(session, user_id, key, start, end)
    highlights = [
        f"打卡天数 {stats.days} 天",
        f"摄入 {stats.intake:.0f} kcal",
        f"缺口 {(-stats.deficit):.0f} kcal",
        f"步数 {stats.steps} 步",
    ]
    if not (s.LLM_BASE_URL and s.LLM_API_KEY):
        content = _template_comment(stats)
    else:  # pragma: no cover - 无 Key 环境不触发
        client = llm_client or llm_client_for(s)
        prompt = (
            f"这是用户本周（{key}）的数据：打卡 {stats.days} 天，"
            f"摄入 {stats.intake:.0f} kcal，缺口 {(-stats.deficit):.0f} kcal，"
            f"步数 {stats.steps} 步，体重变化 {stats.weight_change}kg。"
            "请用 2-3 句给出温和、可执行的周点评。"
        )
        content = await generate_reply(client, _build_messages(prompt, []), timeout=s.AI_TIMEOUT)
    if AI_DISCLAIMER not in content:
        content = f"{content}{AI_DISCLAIMER}"
    return WeeklyCommentData(week=key, content=content, highlights=highlights, references=[])
