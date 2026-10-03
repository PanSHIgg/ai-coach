"""拍照识别服务（plan.md BE4a / 06-AI服务.md §2.3、§六）。

链路：图片字节 → 视觉客户端候选 → 逐条匹配 food 表 → 热量换算 → need_confirm 判定。

口径与默认决策：
- 视觉客户端抽象见 `app/ai/base.py`；本服务不绑定厂商，客户端可由调用方注入（测试/降级）。
- 匹配（F1b 修复后口径，见下「food 表匹配」小节）：
  召回 = 完整候选名 + 2 字滑窗词，对 `food.name` / `food_alias.alias` 做 ILIKE 子串
  （SQLAlchemy 2.0 把 `col.ilike()` 渲染成**原生 ILIKE**，trgm GIN 索引对它可用；
  但反向支 `strpos()` 无索引，整条 WHERE 实际仍是**全表扫描**——实测代价与后续解法见
  `match_food_outcome` 上方注释，勿按"已走索引"做性能规划）+
  反向包含（候选名整条包含更短食物名）；
  排序 = `greatest(similarity(name, kw), max similarity(alias, kw))` + 名称精确命中优先；
  采纳 = **显式阈值** `AUTO_ACCEPT_SIMILARITY` 且领先次优 `AUTO_ACCEPT_MARGIN`，
  否则不自动选 top1，回 `candidates` 交调用方让用户确认（§6.3.2 置信度不足需确认的同一口径）。
  与 `record_service.search_food`（G10）同库同索引，但**识别路径多一道阈值**——识别是自动写账，
  搜索是给人挑，后者无需保守。
- 热量：命中 → `food.calories_100g × amount_g / 100`；未命中 → 模型给的 `kcal_100g`（缺失时兜底
  `FALLBACK_KCAL_100G`）。两者均 round 1 位，与 `record_service._nutrition` 一致。
- need_confirm：任一条 `confidence < AI_CONFIDENCE_THRESHOLD`（默认 0.7）**或**未自动命中 food
  表（含"召回了但不确定"）→ True。
- 响应携带确认信息（契约已扩字段）：`items[].ambiguous` + `items[].candidates`——不确定项带回
  召回候选让用户选，库里真没有的是 `ambiguous=false, candidates=[]`（见 `build_item`）。
- 最多返回 `MAX_ITEMS` 条；入参与候选均做上限收敛，避免模型返回长列表。

【主 Agent 决策（Phase 2）】`RecognizedItem.food_id` 已在 schemas/record.py、openapi.yaml 与两份 TS
副本中统一改为 **nullable**：未命中食物表时为 `None`（而非哨兵 0），语义与 need_confirm 一致。
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import VisionClient
from app.ai.mock import MockVisionClient
from app.core.config import Settings, get_settings
from app.core.errors import AppException
from app.models import Food, FoodAlias
from app.schemas.common import ErrorCode
from app.schemas.record import MatchCandidate, RecognizeData, RecognizedItem
from app.services.ai_service import _escape_like, _OpenAICompatVLM, _terms

MAX_ITEMS = 5
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5MB（契约/任务书口径）
UNMATCHED_FOOD_ID = None  # 未命中 food 表：food_id 为 null（契约已改 nullable）
DEFAULT_PORTION_G = 150.0  # 6.x vision.py 同口径：接口不给份量时按 150g 估
FALLBACK_KCAL_100G = 200.0  # 模型未给 kcal_100g 时的粗估值（vision.py 同口径）

# ---- 匹配采纳阈值（F1b：实测标定，改动须同步 test_recognize_matching.py 的标定用例）----
MAX_MATCH_CANDIDATES = 3  # 不确定时带回给调用方/前端确认的候选上限
MATCH_TERMS_MAX = 8  # **滑窗词**上限（同 RAG 路径 _terms）；整条候选名另计，召回词总数 ≤ 8+1=9
AUTO_ACCEPT_SIMILARITY = 0.5
AUTO_ACCEPT_MARGIN = 0.05


@dataclass(frozen=True)
class Candidate:
    """归一化后的视觉候选条目（屏蔽不同厂商返回形态差异）。"""

    name: str
    confidence: float
    portion_g: float
    kcal_100g: float


@dataclass(frozen=True)
class MatchedFood:
    """命中行的最小子集（便于纯逻辑单测脱离 DB 构造）。"""

    id: int
    name: str
    calories_100g: float


@dataclass(frozen=True)
class RecallRow:
    """召回后带分数的候选行（`score` 为 name/alias 的 pg_trgm 相似度较大者）。

    `exact` 指 `food.name` 与候选名逐字相等——唯一可无条件采纳的情形（等价于人工录入）。
    纯内部行（含 `exact`）；出参用契约模型 `schemas.record.MatchCandidate`，二者不要混名。
    """

    id: int
    name: str
    calories_100g: float
    score: float
    exact: bool

    def as_matched(self) -> MatchedFood:
        return MatchedFood(id=self.id, name=self.name, calories_100g=self.calories_100g)


@dataclass(frozen=True)
class MatchOutcome:
    """一次匹配的结果：自动采纳项（可能为 None）+ 供用户确认的候选列表。

    - `matched is None and candidates` → 召回到了但不确定（分数不够 / 并列），调用方应让用户选
      （识别响应里以 `ambiguous=true` + `candidates` 外显，见 `build_item`）；
    - `not candidates` → 库里确实没有（§2.4：回落模型估算 + 人工搜索）。
    `ambiguous` 区分这两种 None：既给 `need_confirm` 之外的前端确认分支用，也用来决定响应里
    是否带候选。
    """

    matched: MatchedFood | None
    candidates: list[RecallRow]
    ambiguous: bool


# ---------------------------------------------------------------------------
# 入参校验
# ---------------------------------------------------------------------------


def ensure_valid_image(image_bytes: bytes, content_type: str | None) -> None:
    """图片入参校验：空文件 / 非图片类型 / 超过 5MB → 2001(422)。"""
    if not image_bytes:
        raise AppException(ErrorCode.VALIDATION_ERROR, "请上传食物照片")
    if not (content_type or "").lower().startswith("image/"):
        raise AppException(ErrorCode.VALIDATION_ERROR, "仅支持图片文件")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise AppException(ErrorCode.VALIDATION_ERROR, "图片不能超过 5MB")


# ---------------------------------------------------------------------------
# 纯逻辑（可脱离网络/DB 单测）
# ---------------------------------------------------------------------------


def _as_float(value: object) -> float:
    """视觉返回的数值字段可能是 int/float/str/None；非法值按 0 处理。"""
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def normalize_candidates(raw_items: list[dict] | None) -> list[Candidate]:
    """视觉原始条目 → 归一化候选（最多 MAX_ITEMS 条，无名称者丢弃）。

    兼容两种返回形态：VLM `{portion_g, kcal_100g}` 与 Mock `{calorie_estimate}`（只给总 kcal）。
    """
    items: list[Candidate] = []
    for raw in (raw_items or [])[:MAX_ITEMS]:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        confidence = min(max(_as_float(raw.get("confidence")), 0.0), 1.0)
        portion_g = _as_float(raw.get("portion_g"))
        if portion_g <= 0:
            portion_g = DEFAULT_PORTION_G
        kcal_100g = _as_float(raw.get("kcal_100g"))
        if kcal_100g <= 0:
            estimate = _as_float(raw.get("calorie_estimate"))
            kcal_100g = round(estimate / portion_g * 100, 1) if estimate > 0 else FALLBACK_KCAL_100G
        items.append(
            Candidate(
                name=name,
                confidence=round(confidence, 2),
                portion_g=portion_g,
                kcal_100g=kcal_100g,
            )
        )
    return items


def compute_calories(kcal_100g: float, amount_g: float) -> float:
    """每 100g 热量 × 分量 → kcal（与 record_service._nutrition 同口径，round 1 位）。"""
    return round(kcal_100g * amount_g / 100.0, 1)


def _to_out_candidates(rows: Sequence[RecallRow]) -> list[MatchCandidate]:
    """内部候选行 → 契约 `MatchCandidate`（字段名 `id` → `food_id`，`exact` 不外泄）。"""
    return [
        MatchCandidate(food_id=r.id, name=r.name, calories_100g=r.calories_100g, score=r.score)
        for r in rows
    ]


def build_item(
    candidate: Candidate,
    matched: MatchedFood | None,
    *,
    ambiguous: bool = False,
    candidates: Sequence[RecallRow] = (),
) -> RecognizedItem:
    """候选 → 识别条目；热量来源取决于是否命中食物表。

    `ambiguous` / `candidates` 的响应口径（openapi `RecognizedItem`，§6.3.2 置信度不足需确认）：
    - 自动命中 → `food_id` 有值、`ambiguous=false`、`candidates=[]`
      （契约明写"food_id 已自动命中时为空数组"；`MatchOutcome.candidates` 里那些召回行是
      给 `decide_match` 判并列/反例用的内部审计，不外泄给前端，避免与已采纳项打架）；
    - 召回到了但不确定（分数不足 / 并列 / 同名多行）→ `food_id=null`、`ambiguous=true`、
      `candidates` 非空，前端让用户从里头挑（§6.3.2）；
    - 库里确实没有 → `food_id=null`、`ambiguous=false`、`candidates=[]`，走 §2.4
      （回落模型估算 + 手动搜索 / 自定义食物）。
    后两类都不改既有字段语义：`name`/`calories` 仍是"未命中时按模型估算"，老客户端忽略新字段即可。
    """
    if matched is not None:
        return RecognizedItem(
            food_id=matched.id,
            name=matched.name,
            confidence=candidate.confidence,
            amount_g=candidate.portion_g,
            calories=compute_calories(matched.calories_100g, candidate.portion_g),
            ambiguous=False,
            candidates=[],
        )
    return RecognizedItem(
        food_id=UNMATCHED_FOOD_ID,
        name=candidate.name,
        confidence=candidate.confidence,
        amount_g=candidate.portion_g,
        calories=compute_calories(candidate.kcal_100g, candidate.portion_g),
        ambiguous=ambiguous,
        candidates=_to_out_candidates(candidates),
    )


def resolve_need_confirm(items: list[RecognizedItem], threshold: float) -> bool:
    """任一条置信度低于阈值，或有条目未匹配到 food 表 → True（06 文档 §六）。"""
    return any(item.confidence < threshold or item.food_id is None for item in items)


# ---------------------------------------------------------------------------
# food 表匹配
# ---------------------------------------------------------------------------


def recall_terms(kw: str) -> list[str]:
    """召回词：完整候选名 + 2 字滑窗（复用 RAG 路径的 `_terms`）。

    截断口径以实现为准：`_terms` 先给最多 `MATCH_TERMS_MAX`(8) 个滑窗词，整条候选名**另计**
    再排最前，去重后整体截 `MATCH_TERMS_MAX + 1`(=9) 条——即"整条名 + 8 个滑窗词"，
    不是"总共 8 条"（识别一次最多 MAX_ITEMS 条候选，每条最多 9 个 ILIKE 支，见上面的代价说明）。

    只按整条候选名做子串召回会漏掉「清蒸鱼 → 清蒸鲈鱼」这类泛化菜名（子串互不包含），
    滑窗词是唯一的中文切词手段（`simple` tsvector 不切中文，故 §6.3.2 的 search_vec 在此不管用）。
    """
    terms = list(dict.fromkeys([kw.strip(), *_terms(kw, max_terms=MATCH_TERMS_MAX)]))
    return [t for t in terms if t.strip()][: MATCH_TERMS_MAX + 1]


def decide_match(
    rows: Sequence[RecallRow],
    *,
    threshold: float = AUTO_ACCEPT_SIMILARITY,
    margin: float = AUTO_ACCEPT_MARGIN,
) -> MatchOutcome:
    """纯决策（无 DB）：只有"名称精确"或"过阈值且明显领先次优"才自动采纳，否则交候选确认。

    实测标定（本机 ai_coach 库，pg_trgm default，2026-10-02 实跑）：
    - 应当命中的泛化菜名在**无别名**时最高只有 0.2857（清蒸鱼↔清蒸鲈鱼）、
      0.25（红烧肉↔红烧猪五花），而**不该命中的**清蒸姜/清蒸葱对"清蒸鱼"是 0.3333——
      即相似度排序在这里是**反向**的，任何"取 top1"的策略（旧实现）都会把
      105kcal 的清蒸鲈鱼猜成 41kcal 的清蒸姜；
    - 因此阈值必须 > 0.3334（挡掉清蒸姜/葱），取 0.5 留出余量，同时仍允许真正的同族菜名过线
      （标定用例 土豆炖牛肉↔土豆炖牛腩 = 0.5；当前种子库无「土豆炖牛腩」行，
      真实召回最高只有 0.2857（土豆）→ 落到 candidates 交用户确认）；
    - `margin` 处理并列（清蒸姜/清蒸葱同为 0.3333），并列即不确定，不猜。
    种子库只对**语义成立**的泛化名补别名（清蒸鱼/蒸鱼→清蒸鲈鱼、红烧肉/红烧猪肉→红烧猪五花、
    白饭→白米饭），这些以 `alias` 精确命中拿到 1.0，走的是同一条规则，不需要特例；
    错配别名（番茄炒蛋→鸡蛋 等）已撤销，宁可让用户确认也不写错账。
    """
    if not rows:
        return MatchOutcome(matched=None, candidates=[], ambiguous=False)
    show = list(rows[:MAX_MATCH_CANDIDATES])
    exact = [r for r in rows if r.exact]
    if len(exact) == 1:  # 名称逐字相等：与人工录入等价，无条件采纳
        return MatchOutcome(matched=exact[0].as_matched(), candidates=show, ambiguous=False)
    if len(exact) > 1:  # 同名多行（name 非唯一约束）：不猜
        return MatchOutcome(matched=None, candidates=show, ambiguous=True)
    top = rows[0]
    runner_up = rows[1].score if len(rows) > 1 else float("-inf")
    if top.score >= threshold and top.score - runner_up >= margin:
        return MatchOutcome(matched=top.as_matched(), candidates=show, ambiguous=False)
    return MatchOutcome(matched=None, candidates=show, ambiguous=True)


async def match_food_outcome(session: AsyncSession, name: str) -> MatchOutcome:
    """候选名 → 匹配结果：双向召回打分后按显式阈值决策（详见 `decide_match`）。"""
    kw = (name or "").strip()
    if not kw:
        return MatchOutcome(matched=None, candidates=[], ambiguous=False)
    terms = recall_terms(kw)
    patterns = [f"%{_escape_like(t)}%" for t in terms]
    # 正向：食物名/别名包含任一召回词；反向：候选名整条包含更短的食物名
    # （如"清蒸鲈鱼二两"→"清蒸鲈鱼"），≥2 字避免单字噪声。
    # 索引事实（本机 ai_coach 1750 行 / pg_trgm default / SQLAlchemy 2.0.54，2026-10-03 实跑
    # EXPLAIN，勿凭印象改）：
    #   · col.ilike() 在本项目渲染成**原生 ILIKE**（~~*），正向支是可走
    #     gin (name/alias gin_trgm_ops) 的形态：SET enable_seqscan=off 后别名子计划确实出现
    #     Bitmap Index Scan on idx_food_alias_trgm（若写成 lower(name) LIKE lower(pat) 则同一
    #     谓词只能 Seq Scan，索引永不可用——别改成那种形态）。
    #   · 但**默认计划仍是 Seq Scan on food**：反向支 strpos(lower(kw), lower(name)) 无索引可用，
    #     OR 上去之后规划器只能全表扫；实测 4.4ms（9 个召回词）/ 1.4ms（1 个词）。
    #   · 风险在增长：food 表由"手动填热量"持续写入自定义行，一次识别最多串 MAX_ITEMS(5) 条
    #     这样的语句。行数上去后要动的是**反向支**（如改走 trgm % 近似匹配或加表达式索引），
    #     正向支本身已经是对的——勿按"已走索引"做性能规划。
    forward = or_(
        *[Food.name.ilike(p, escape="\\") for p in patterns],
        Food.id.in_(
            select(FoodAlias.food_id).where(
                or_(*[FoodAlias.alias.ilike(p, escape="\\") for p in patterns])
            )
        ),
    )
    reverse = and_(
        func.char_length(Food.name) >= 2,
        # strpos(string, substring)：参数序与 position(substring IN string) 相反，写反必 0 命中
        func.strpos(func.lower(kw), func.lower(Food.name)) > 0,
    )
    alias_sim = (
        select(func.max(func.similarity(FoodAlias.alias, kw)))
        .where(FoodAlias.food_id == Food.id)
        .scalar_subquery()
    )
    score = func.greatest(func.similarity(Food.name, kw), func.coalesce(alias_sim, 0.0))
    is_exact = Food.name == kw
    stmt = (
        select(
            Food.id, Food.name, Food.calories_100g,
            score.label("score"), is_exact.label("exact"),
        )
        .where(Food.status == 1, or_(forward, reverse))
        .order_by(is_exact.desc(), score.desc(), Food.id)
        .limit(MAX_MATCH_CANDIDATES + 1)  # 多取 1 条：判定"是否还有并列/更多候选"
    )
    rows = [
        RecallRow(
            id=int(r[0]),
            name=r[1],
            calories_100g=float(r[2]),
            score=round(float(r[3]), 4),
            exact=bool(r[4]),
        )
        for r in (await session.execute(stmt)).all()
    ]
    return decide_match(rows)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def vision_client_for(s: Settings) -> VisionClient:
    """按 env 装配视觉客户端：VLM_BASE_URL+VLM_API_KEY 齐备 → OpenAI 兼容 VLM；
    否则落 Mock（明确降级，见 current.md 的 AI 无 Key 降级口径）。
    """
    if s.VLM_BASE_URL and s.VLM_API_KEY:
        return _OpenAICompatVLM(s.VLM_BASE_URL, s.VLM_API_KEY, s.VLM_MODEL, timeout=s.AI_TIMEOUT)
    return MockVisionClient()


async def recognize(
    session: AsyncSession,
    image_bytes: bytes,
    *,
    request_id: str | None = None,
    settings: Settings | None = None,
    vision_client: VisionClient | None = None,
) -> RecognizeData:
    """拍照识别主流程：视觉候选 → food 表匹配 → 组装 RecognizeData。

    视觉客户端为同步阻塞实现（`VisionClient.recognize_food`），放线程池避免阻塞事件循环；
    任何异常/超时统一降级为 6001「没看清，换个角度再拍或手动搜索」（06 文档 §1.4）。
    """
    s = settings or get_settings()
    client = vision_client or vision_client_for(s)
    try:
        raw_items = await asyncio.to_thread(client.recognize_food, image_bytes)
    except Exception as exc:  # 网络错误/超时/解析失败统一降级
        raise AppException(ErrorCode.AI_UNAVAILABLE, "没看清，换个角度再拍或手动搜索") from exc

    candidates = normalize_candidates(raw_items)
    # 取完整匹配结果而不只是自动采纳项：不确定的条目把候选一并带回
    # （契约 RecognizedItem.ambiguous / candidates，§6.3.2「置信度不足让用户确认」），
    # 前端据此渲染候选列表；库里确实没有的仍是 ambiguous=false + candidates=[]（§2.4 手动录入）。
    items = []
    for c in candidates:
        outcome = await match_food_outcome(session, c.name)
        items.append(
            build_item(
                c,
                outcome.matched,
                ambiguous=outcome.ambiguous,
                candidates=outcome.candidates,
            )
        )
    return RecognizeData(
        request_id=request_id or uuid.uuid4().hex,
        items=items,
        need_confirm=resolve_need_confirm(items, s.AI_CONFIDENCE_THRESHOLD),
    )
