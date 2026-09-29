"""饭点决策推荐服务（plan.md §8 BE4c / 03 文档 §5.2「吃什么」页）。

链路：餐次 → 今日剩余热量额度 → food 表候选 → 2~3 个组合 → 绿/黄/红健康等级 → 推荐理由。

口径与默认决策（docs/split/10 零提问默认决策规则）：
- **剩余额度**：复用 `services.account.compute_result` → `calorie.CalorieResult.today_left`
  （= 预算 − 摄入 + 运动 − TEF，与首页环形图同口径），再与该餐次默认额度取小
  （单餐不应吃掉全天余额）。未建档（account 抛 3001）→ 直接用餐次默认额度。
- **餐次默认额度**：早餐 400 / 午餐 600 / 晚餐 500 / 加餐 200 kcal（任务书给定）。
- **组合**：主食 / 蛋白 / 蔬菜三类按份量拼装；候选优先 `is_standard=true`，其次 id 升序（稳定）。
- **等级**：总热量 ≤ 额度 → 绿；≤ 额度×1.2 → 黄；否则红；额度 ≤ 0 一律红。
  等级语义写进 `reason` 前缀（"[推荐]" / "[可接受]" / "[建议少吃]"）——
  契约 `RecommendOption` 只有 food_id/name/calories/reason/merchant_id，不臆造字段。
- **LLM 只润色推荐语**：任何失败（含获取客户端失败、超时、条数不符）一律静默降级为规则文案，
  **本接口不得因 AI 不可用而返回 6001**。
- **budget / location**：food 表无价格列、商家域属 Phase 3，现阶段忽略（只作日志）。
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import factory
from app.ai.base import LLMClient
from app.ai.prompts import AI_COACH_SYSTEM_PROMPT
from app.core.config import Settings, get_settings
from app.core.errors import AppException
from app.core.logging import get_logger
from app.models import Food
from app.schemas.ai import GeoLocation, RecommendOption
from app.services import account
from app.services.recognize_service import compute_calories

logger = get_logger(__name__)

TZ = timezone(timedelta(hours=8))

# 未建档/无快照时的餐次默认额度（kcal）：1早餐 2午餐 3晚餐 4加餐
MEAL_DEFAULT_KCAL: dict[int, float] = {1: 400.0, 2: 600.0, 3: 500.0, 4: 200.0}
DEFAULT_MEAL_KCAL = 500.0

YELLOW_TOLERANCE = 1.2  # 黄灯：超出剩余额度 ≤ 20%
MAX_REASON_LEN = 40  # LLM 润色文案长度上限，超出视为不可用

# 等级标签即 reason 前缀（契约无等级字段，语义落文案）
GREEN_TAG = "[推荐]"
YELLOW_TAG = "[可接受]"
RED_TAG = "[建议少吃]"


class Grade(NamedTuple):
    """健康等级：标签（写进 reason）+ 规则建议语。"""

    tag: str
    advice: str


GREEN = Grade(GREEN_TAG, "剩余额度充足")
YELLOW = Grade(YELLOW_TAG, "略高于剩余额度，建议主食减半")
RED = Grade(RED_TAG, "明显超出剩余额度，建议减少份量或改选蔬菜")


class Slot(NamedTuple):
    """组合中的一格：候选类目 + 份量（g）。"""

    categories: tuple[str, ...]
    grams: float


class ComboTemplate(NamedTuple):
    """组合模板：标签 + 卖点 + 各格构成。"""

    label: str
    highlight: str
    slots: tuple[Slot, ...]


# 各模板的候选类目顺序不同：保证三个组合主打食物不重复（否则三张卡长得一样）
STAPLE_CATEGORIES = ("主食",)
MEAT_FIRST = ("肉类", "水产", "蛋类", "豆制品")
SEAFOOD_FIRST = ("水产", "蛋类", "豆制品", "肉类")
BEAN_FIRST = ("豆制品", "水产", "蛋类", "肉类")
VEGGIE_FIRST = ("蔬菜", "菌藻")
FUNGUS_FIRST = ("菌藻", "蔬菜")

COMBO_TEMPLATES: tuple[ComboTemplate, ...] = (
    ComboTemplate(
        label="高蛋白组合",
        highlight="蛋白足、饱腹感强",
        slots=(
            Slot(MEAT_FIRST, 200.0),
            Slot(VEGGIE_FIRST, 200.0),
            Slot(STAPLE_CATEGORIES, 100.0),
        ),
    ),
    ComboTemplate(
        label="均衡组合",
        highlight="主食+蛋白+蔬菜配比均衡",
        slots=(
            Slot(STAPLE_CATEGORIES, 150.0),
            Slot(SEAFOOD_FIRST, 120.0),
            Slot(VEGGIE_FIRST, 200.0),
        ),
    ),
    ComboTemplate(
        label="低碳组合",
        highlight="低碳水，血糖波动小",
        slots=(
            Slot(BEAN_FIRST, 150.0),
            Slot(FUNGUS_FIRST, 300.0),
            Slot(STAPLE_CATEGORIES, 50.0),
        ),
    ),
)


@dataclass(frozen=True)
class Combo:
    """一个可推荐的组合（纯数据，便于脱离 DB 单测）。"""

    template: ComboTemplate
    items: tuple[tuple[Food, float], ...]
    calories: float
    name: str
    food_id: int


# ---------------------------------------------------------------------------
# 纯逻辑
# ---------------------------------------------------------------------------


def grade_for(total: float, allowance: float) -> Grade:
    """总热量 vs 剩余额度 → 健康等级（额度 ≤ 0 一律红）。"""
    if allowance <= 0:
        return RED
    if total <= allowance:
        return GREEN
    if total <= allowance * YELLOW_TOLERANCE:
        return YELLOW
    return RED


def build_reason(tag: str, body: str) -> str:
    """等级前缀 + 推荐语正文（等级语义只能落在文案里）。"""
    return f"{tag} {body}"


def rule_body(combo: Combo, grade: Grade) -> str:
    """规则推荐语正文：组合卖点 + 热量 + 建议。"""
    return (
        f"{combo.template.label}：{combo.template.highlight}，"
        f"约 {int(combo.calories)} kcal，{grade.advice}"
    )


def _parse_reasons(text: str, expected: int) -> list[str] | None:
    """LLM 返回 → 逐行推荐语；条数不符 / 空行 / 过长视为不可用（降级）。"""
    lines: list[str] = []
    for raw in (text or "").splitlines():
        line = re.sub(r"^\s*(?:\d+[.、)]|[-•*])\s*", "", raw).strip()
        if not line:
            continue
        lines.append(line)
    if len(lines) != expected or any(len(line) > MAX_REASON_LEN for line in lines):
        return None
    return lines


def _prompt(combos: list[Combo], allowance: float, budget: float | None) -> list[dict]:
    """润色提示词：一条组合一行，要求按同序输出等长行数。"""
    lines = [
        f"{i}. {c.name}，约 {int(c.calories)} kcal，{c.template.highlight}"
        for i, c in enumerate(combos, start=1)
    ]
    budget_hint = f"人均预算 {budget:g} 元；" if budget else ""
    question = (
        f"用户这一餐剩余热量额度约 {int(allowance)} kcal，{budget_hint}"
        f"以下是 {len(combos)} 个候选组合：\n" + "\n".join(lines) + "\n"
        "请为每个组合各写一句不超过 25 个字的中文推荐理由，"
        "按上面同样的顺序、每行一条，不要编号、不要多余解释。"
    )
    return [
        {"role": "system", "content": AI_COACH_SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]


# ---------------------------------------------------------------------------
# 额度与候选
# ---------------------------------------------------------------------------


async def remaining_allowance(session: AsyncSession, user_id: int, meal_type: int) -> float:
    """本餐可用额度 = min(今日剩余额度, 餐次默认额度)；未建档 → 餐次默认额度。"""
    meal_default = MEAL_DEFAULT_KCAL.get(meal_type, DEFAULT_MEAL_KCAL)
    try:
        result = await account.compute_result(session, user_id, datetime.now(TZ).date())
    except AppException:  # 3001 未建档/体重缺失
        logger.info("未建档，推荐按餐次默认额度", extra={"user_id": user_id})
        return meal_default
    return min(float(result.today_left), meal_default)


async def _pick_food(
    session: AsyncSession, slot: Slot, cache: dict[str, Food | None]
) -> Food | None:
    """按类目优先级取一条候选：类目顺序 → 标准食物优先 → id 升序（结果稳定可复现）。

    同一类目只查一次（`cache` 跨组合复用），避免每格都打一次库。
    """
    for category in slot.categories:
        if category not in cache:
            stmt = (
                select(Food)
                .where(Food.status == 1, Food.category == category)
                .order_by(Food.is_standard.desc(), Food.id)
                .limit(1)
            )
            cache[category] = (await session.execute(stmt)).scalar_one_or_none()
        if cache[category] is not None:
            return cache[category]
    return None


async def build_combos(session: AsyncSession) -> list[Combo]:
    """全部模板 → 组合（按总热量升序）；整组无候选的模板跳过。"""
    cache: dict[str, Food | None] = {}
    combos: list[Combo] = []
    for template in COMBO_TEMPLATES:
        items: list[tuple[Food, float]] = []
        for slot in template.slots:
            food = await _pick_food(session, slot, cache)
            if food is not None:
                items.append((food, slot.grams))
        if not items:
            continue
        calories = round(
            sum(compute_calories(float(food.calories_100g), grams) for food, grams in items), 1
        )
        main = max((food for food, _ in items), key=lambda f: float(f.protein_100g or 0))
        combos.append(
            Combo(
                template=template,
                items=tuple(items),
                calories=calories,
                name=" + ".join(food.name for food, _ in items),
                food_id=int(main.id),
            )
        )
    combos.sort(key=lambda c: c.calories)
    return combos




# ---------------------------------------------------------------------------
# LLM 润色（失败即降级）
# ---------------------------------------------------------------------------


async def _invoke(client: LLMClient, messages: list[dict]) -> str:
    """兼容异步/同步客户端：`achat` 优先，否则同步 `chat` 放线程池。"""
    achat = getattr(client, "achat", None)
    if callable(achat):
        return await achat(messages)
    return await asyncio.to_thread(client.chat, messages)


async def polish_reasons(
    client: LLMClient,
    combos: list[Combo],
    allowance: float,
    budget: float | None,
    timeout: float,
) -> list[str] | None:
    """调 LLM 润色推荐语；返回与 combos 等长的正文列表，不可用返回 None。"""
    text = await asyncio.wait_for(
        _invoke(client, _prompt(combos, allowance, budget)), timeout=timeout
    )
    return _parse_reasons(text, len(combos))


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


async def recommend(
    session: AsyncSession,
    settings: Settings | None,
    user_id: int,
    meal_type: int,
    location: GeoLocation | None = None,
    budget: float | None = None,
    llm_client: LLMClient | None = None,
) -> list[RecommendOption]:
    """饭点决策主流程：额度 → 组合 → 分级 → 润色（失败降级）。

    budget / location 现阶段无数据支撑（food 无价格列、商家域 Phase 3），只记录日志。
    """
    s = settings or get_settings()
    if budget is not None or location is not None:
        logger.info("推荐收到预算/位置参数，Phase 3 才接入价格与商家，本轮忽略")

    allowance = await remaining_allowance(session, user_id, meal_type)
    combos = await build_combos(session)
    grades = [grade_for(combo.calories, allowance) for combo in combos]

    bodies: list[str] | None = None
    if combos:
        try:
            client = llm_client or factory.get_llm_client(s)
            bodies = await polish_reasons(client, combos, allowance, budget, s.MS_TIMEOUT)
        except Exception as exc:  # noqa: BLE001 - AI 不可用只降级，不阻断推荐
            logger.warning("推荐语润色失败，降级规则文案", extra={"reason": str(exc)})
    if bodies is None:
        bodies = [rule_body(combo, grade) for combo, grade in zip(combos, grades, strict=True)]

    return [
        RecommendOption(
            food_id=combo.food_id,
            name=combo.name,
            calories=combo.calories,
            reason=build_reason(grade.tag, body),
            merchant_id=None,
        )
        for combo, grade, body in zip(combos, grades, bodies, strict=True)
    ]
