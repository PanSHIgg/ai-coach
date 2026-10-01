"""拍照识别服务（plan.md BE4a / 06-AI服务.md §2.3、§六）。

链路：图片字节 → 视觉客户端候选 → 逐条匹配 food 表 → 热量换算 → need_confirm 判定。

口径与默认决策：
- 视觉客户端抽象见 `app/ai/base.py`；本服务不绑定厂商，客户端可由调用方注入（测试/降级）。
- 匹配优先级：`food.name` 精确 → `food.name` ILIKE → `food_alias.alias` ILIKE（仅 status=1），
  写法对齐 `record_service.search_food`（Chinese 场景不切词，靠 ILIKE 子串兜底）。
- 热量：命中 → `food.calories_100g × amount_g / 100`；未命中 → 模型给的 `kcal_100g`（缺失时兜底
  `FALLBACK_KCAL_100G`）。两者均 round 1 位，与 `record_service._nutrition` 一致。
- need_confirm：任一条 `confidence < AI_CONFIDENCE_THRESHOLD`（默认 0.7）**或**未匹配到 food
  表 → True。
- 最多返回 `MAX_ITEMS` 条；入参与候选均做上限收敛，避免模型返回长列表。

【主 Agent 决策（Phase 2）】`RecognizedItem.food_id` 已在 schemas/record.py、openapi.yaml 与两份 TS
副本中统一改为 **nullable**：未命中食物表时为 `None`（而非哨兵 0），语义与 need_confirm 一致。
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import VisionClient
from app.ai.mock import MockVisionClient
from app.core.config import Settings, get_settings
from app.core.errors import AppException
from app.models import Food, FoodAlias
from app.schemas.common import ErrorCode
from app.schemas.record import RecognizeData, RecognizedItem
from app.services.ai_service import _OpenAICompatVLM

MAX_ITEMS = 5
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5MB（契约/任务书口径）
UNMATCHED_FOOD_ID = None  # 未命中 food 表：food_id 为 null（契约已改 nullable）
DEFAULT_PORTION_G = 150.0  # 6.x vision.py 同口径：接口不给份量时按 150g 估
FALLBACK_KCAL_100G = 200.0  # 模型未给 kcal_100g 时的粗估值（vision.py 同口径）


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


def build_item(candidate: Candidate, matched: MatchedFood | None) -> RecognizedItem:
    """候选 → 识别条目；热量来源取决于是否命中食物表。"""
    if matched is not None:
        return RecognizedItem(
            food_id=matched.id,
            name=matched.name,
            confidence=candidate.confidence,
            amount_g=candidate.portion_g,
            calories=compute_calories(matched.calories_100g, candidate.portion_g),
        )
    return RecognizedItem(
        food_id=UNMATCHED_FOOD_ID,
        name=candidate.name,
        confidence=candidate.confidence,
        amount_g=candidate.portion_g,
        calories=compute_calories(candidate.kcal_100g, candidate.portion_g),
    )


def resolve_need_confirm(items: list[RecognizedItem], threshold: float) -> bool:
    """任一条置信度低于阈值，或有条目未匹配到 food 表 → True（06 文档 §六）。"""
    return any(item.confidence < threshold or item.food_id is None for item in items)


# ---------------------------------------------------------------------------
# food 表匹配
# ---------------------------------------------------------------------------


async def _lookup_food(
    session: AsyncSession, *conds, join_alias: bool = False
) -> MatchedFood | None:
    """按条件取一条 status=1 的食物（id 最小者），未命中返回 None。"""
    stmt = select(Food.id, Food.name, Food.calories_100g).where(Food.status == 1, *conds)
    if join_alias:
        stmt = stmt.join(FoodAlias, FoodAlias.food_id == Food.id)
    row = (await session.execute(stmt.order_by(Food.id).limit(1))).first()
    if row is None:
        return None
    return MatchedFood(id=int(row[0]), name=row[1], calories_100g=float(row[2]))


async def match_food(session: AsyncSession, name: str) -> MatchedFood | None:
    """食物名 → food 表行：name 精确 → name ILIKE → alias ILIKE。"""
    kw = (name or "").strip()
    if not kw:
        return None
    for conds, join_alias in (
        ((Food.name == kw), False),
        ((Food.name.ilike(f"%{kw}%")), False),
        ((FoodAlias.alias.ilike(f"%{kw}%"), True)),
    ):
        matched = await _lookup_food(session, conds, join_alias=join_alias)
        if matched is not None:
            return matched
    return None


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def vision_client_for(s: Settings) -> VisionClient:
    """按 env 装配视觉客户端：VLM_BASE_URL+VLM_API_KEY 齐备 → OpenAI 兼容 VLM；否则 Mock（明确降级）。"""
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
    items = [build_item(c, await match_food(session, c.name)) for c in candidates]
    return RecognizeData(
        request_id=request_id or uuid.uuid4().hex,
        items=items,
        need_confirm=resolve_need_confirm(items, s.AI_CONFIDENCE_THRESHOLD),
    )
