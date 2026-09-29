"""AI 对话服务：次数配额 + RAG 检索 + LLM 生成 + 对话落库 + 降级免责。

真源 `docs/split/06-AI服务.md`：
- §2.3 系统提示词固定"AI 饮食教练"身份，只答体重管理、疾病引导就医；
- §2.4 AI 对话限流 20 次/分钟/用户；
- §4.3 返回结构 `{reply, intent, times_left, references}`；
- §4.4 次数用尽返 4001（"今日对话次数已用完，邀请好友可解锁更多"）；
- §六 所有 AI 输出带免责声明；服务不可用/超时降级预设 FAQ（6001），不卡死。

日期口径：业务日界 UTC+8，与 `app/services/account.py` 一致。
"""

from __future__ import annotations

import asyncio
import re
import uuid
from datetime import UTC, date, datetime, time, timedelta, timezone
from typing import NamedTuple

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import factory
from app.ai.base import LLMClient
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
    """RAG 检索 top-K：先 PG 全文检索 `search_vec`，无命中降级 ILIKE；失败按无引用继续。"""
    terms = _terms(query)
    if not terms:
        return []
    tsquery = func.plainto_tsquery("simple", " ".join(terms))
    try:
        rows = (
            (
                await session.execute(
                    select(AiKnowledge)
                    .where(AiKnowledge.search_vec.op("@@")(tsquery))
                    .order_by(func.ts_rank(AiKnowledge.search_vec, tsquery).desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        if rows:
            return list(rows)
    except Exception:  # noqa: BLE001 - 检索异常须降级，不得中断对话
        logger.warning("知识库全文检索失败，降级 ILIKE")
    try:
        matched = or_(
            *[
                column.ilike(f"%{_escape_like(t)}%", escape="\\")
                for t in terms
                for column in (AiKnowledge.content, AiKnowledge.title)
            ]
        )
        stmt = select(AiKnowledge).where(matched).order_by(AiKnowledge.id).limit(limit)
        rows = (await session.execute(stmt)).scalars().all()
        return list(rows)
    except Exception:  # noqa: BLE001 - 兜底也失败则返回空引用
        logger.warning("知识库 ILIKE 检索失败，本次无引用")
        return []


def _build_messages(message: str, docs: list[AiKnowledge]) -> list[dict]:
    """系统提示词 + RAG 上下文 + 用户提问（OpenAI messages 格式）。"""
    messages: list[dict] = [{"role": "system", "content": AI_COACH_SYSTEM_PROMPT}]
    if docs:
        context = "\n".join(f"- {d.title or ''}: {d.content}" for d in docs)
        messages.append({"role": "system", "content": f"可参考下列知识库内容回答：\n{context}"})
    messages.append({"role": "user", "content": message})
    return messages


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
    """取次数行：不存在按 `AI_DAILY_TIMES` 初始化；`ai_times_reset_at` 早于今日 00:00 时重置。

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
            ai_times_left=s.AI_DAILY_TIMES,
            ai_times_reset_at=now,
        )
        session.add(benefit)
        await session.flush()  # 不提交：与 chat() 的扣减同事务，避免提前放锁
        return benefit
    today_start = datetime.combine(datetime.now(TZ).date(), time.min, tzinfo=TZ)
    if benefit.ai_times_reset_at is None or benefit.ai_times_reset_at < today_start:
        benefit.ai_times_left = s.AI_DAILY_TIMES
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
    if int(benefit.ai_times_left) <= 0:
        raise AppException(ErrorCode.QUOTA_EXCEEDED, NO_TIMES_MESSAGE)

    intent = classify_intent(message)
    docs = await retrieve_knowledge(session, message)
    references = [f"knowledge:{d.id}" for d in docs]

    client = llm_client or factory.get_llm_client(s)
    model = str(getattr(client, "model", "") or type(client).__name__)[:64]
    dialog_session_id = _as_uuid(session_id)
    reply = await generate_reply(client, _build_messages(message, docs), timeout=s.MS_TIMEOUT)

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
    if not s.MS_API_KEY:
        content = _template_comment(stats)
    else:  # pragma: no cover - 无 Key 环境不触发
        client = llm_client or factory.get_llm_client(s)
        prompt = (
            f"这是用户本周（{key}）的数据：打卡 {stats.days} 天，"
            f"摄入 {stats.intake:.0f} kcal，缺口 {(-stats.deficit):.0f} kcal，"
            f"步数 {stats.steps} 步，体重变化 {stats.weight_change}kg。"
            "请用 2-3 句给出温和、可执行的周点评。"
        )
        content = await generate_reply(client, _build_messages(prompt, []), timeout=s.MS_TIMEOUT)
    if AI_DISCLAIMER not in content:
        content = f"{content}{AI_DISCLAIMER}"
    return WeeklyCommentData(week=key, content=content, highlights=highlights, references=[])
