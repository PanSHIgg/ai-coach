"""饭点决策推荐服务（docs/split/03-页面布局与交互说明.md §5.2「吃什么」页）。

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
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

from sqlalchemy import literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import LLMClient
from app.ai.prompts import AI_COACH_SYSTEM_PROMPT
from app.services.ai_service import llm_client_for
from app.core.config import Settings, get_settings
from app.core.errors import AppException
from app.core.logging import get_logger
from app.models import Food, FoodAlias
from app.observability.metrics import ai_task
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


# 纯逻辑


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


# LLM 结构化搭配：候选清单喂给模型，输出严格 JSON（ids/grams/reason）；
# 后端按 id 回查 DB 重算热量与等级——LLM 只做搭配决策，不产生任何可信数字。


def _candidate_view(foods: list[Food]) -> list[dict]:
    """候选清单（全部来自 DB 的结构化事实，杜绝 LLM 编造库外食物）。"""
    return [
        {
            "id": int(f.id),
            "name": f.name,
            "category": f.category or "",
            "kcal_100g": round(float(f.calories_100g), 1),
            "protein_100g": round(float(f.protein_100g or 0), 1),
        }
        for f in foods
    ]


def _structured_prompt(
    candidates: list[dict], allowance: float, meal_type: int, budget: float | None
) -> list[dict]:
    meal = {1: "早餐", 2: "午餐", 3: "晚餐", 4: "加餐"}.get(meal_type, "正餐")
    lines = [
        f"{c['id']}|{c['name']}|{c['category']}|{c['kcal_100g']}kcal/100g|蛋白{c['protein_100g']}"
        for c in candidates
    ]
    budget_hint = f"人均预算 {budget:g} 元；" if budget else ""
    question = (
        f"用户这一餐（{meal}）剩余热量额度约 {int(allowance)} kcal，{budget_hint}"
        f"以下是候选食物（id|名称|类别|热量|蛋白质）：\n" + "\n".join(lines) + "\n"
        "请从候选中搭配 3 个组合，让它们分别是：热量明显低于额度的清淡搭配、"
        "接近额度的均衡搭配、允许略超的足量搭配。每个组合 1~3 种食物、"
        "每种克数 50~400g，兼顾荤素与蛋白。严格输出 JSON，不要解释、不要代码块标记，格式："
        '{"combos":[{"ids":[候选id],"grams":[对应克数],"reason":"不超过25字的中文推荐语"}]}'
    )
    return [
        {"role": "system", "content": AI_COACH_SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]


def _extract_json(text: str) -> dict | None:
    """LLM 输出 → JSON 对象：容忍 ``` 围栏与前后杂文字，截取首尾大括号。"""
    raw = (text or "").strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(raw[start : end + 1])
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _parse_structured(
    text: str, by_id: dict[int, Food]
) -> tuple[list[Combo], list[str]] | None:
    """严格校验结构化输出：id 必须在候选内、组合 2~3 个、每组合 1~4 种、克数 0~400、
    理由非空且 ≤40 字；任何不合法 → None（调用方降级规则组合）。"""
    data = _extract_json(text)
    if data is None:
        return None
    entries = data.get("combos")
    if not isinstance(entries, list) or not 2 <= len(entries) <= 3:
        return None
    combos: list[Combo] = []
    reasons: list[str] = []
    shared_template = ComboTemplate(label="推荐组合", highlight="", slots=())
    for entry in entries:
        if not isinstance(entry, dict):
            return None
        raw_ids = entry.get("ids")
        raw_grams = entry.get("grams")
        reason = str(entry.get("reason", "")).strip()
        if not isinstance(raw_ids, list) or not isinstance(raw_grams, list):
            return None
        if not 1 <= len(raw_ids) <= 4 or len(raw_grams) != len(raw_ids):
            return None
        if not reason or len(reason) > MAX_REASON_LEN:
            return None
        chosen: list[tuple[Food, float]] = []
        seen_ids: set[int] = set()
        for rid, gram in zip(raw_ids, raw_grams):
            try:
                fid = int(rid)
                grams = float(gram)
            except (TypeError, ValueError):
                return None
            food = by_id.get(fid)
            if food is None or grams <= 0 or grams > 400 or fid in seen_ids:
                return None
            seen_ids.add(fid)
            chosen.append((food, grams))
        if not chosen:
            return None
        combos.append(
            Combo(
                template=shared_template,
                items=tuple(chosen),
                calories=round(
                    sum(compute_calories(float(f.calories_100g), g) for f, g in chosen), 1
                ),
                name=" + ".join(f.name for f, _ in chosen),
                food_id=int(max(chosen, key=lambda pair: float(pair[0].protein_100g or 0))[0].id),
            )
        )
        reasons.append(reason)
    if not combos:
        return None
    combos.sort(key=lambda c: c.calories)
    return combos, reasons


async def structured_combos(
    client: LLMClient,
    foods: list[Food],
    allowance: float,
    meal_type: int,
    budget: float | None,
    timeout: float,
) -> tuple[list[Combo], list[str]] | None:
    """LLM 结构化搭配主调用：合法返回（组合, 理由），否则 None（降级规则组合）。"""
    text = await asyncio.wait_for(
        _invoke(
            client,
            _structured_prompt(_candidate_view(foods), allowance, meal_type, budget),
        ),
        timeout=timeout,
    )
    by_id = {int(f.id): f for f in foods}
    return _parse_structured(text, by_id)


# 额度与候选


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


STANDARD_CATEGORIES = ("主食", "肉类", "水产", "蛋类", "豆制品", "蔬菜", "菌藻")


async def _standard_candidates(session: AsyncSession) -> list[Food]:
    """无识别结果时的候选池：各关键类目各取 top2（standard 优先、id 升序，结果稳定）。"""
    foods: list[Food] = []
    seen: set[int] = set()
    for category in STANDARD_CATEGORIES:
        stmt = (
            select(Food)
            .where(Food.status == 1, Food.category == category)
            .order_by(Food.is_standard.desc(), Food.id)
            .limit(2)
        )
        for food in (await session.execute(stmt)).scalars():
            if int(food.id) not in seen:
                seen.add(int(food.id))
                foods.append(food)
    return foods


# LLM 润色（失败即降级）


async def _invoke(client: LLMClient, messages: list[dict]) -> str:
    """兼容异步/同步客户端：`achat` 优先，否则同步 `chat` 放线程池。"""
    achat = getattr(client, "achat", None)
    if callable(achat):
        return await achat(messages)
    return await asyncio.to_thread(client.chat, messages)


# 识别菜名 → 食物库匹配（§5.2「菜单拍照识别+推荐」链路）


MATCH_PORTION_G = 200.0  # 识别组合的每菜固定份量（菜单一道菜约 150~250g，取中值）


async def match_foods(session: AsyncSession, names: list[str]) -> list[Food]:
    """菜名 → food 表候选：精确名 → 别名 → 库菜名含于识别名 → 识别名含于库菜名。

    每个菜名取首个命中（standard 优先、id 升序，结果稳定），命中去重保序；
    匹配不上的菜名直接忽略（绝不拿不相干食物冒充），全部未命中返回空列表。
    """
    matched: list[Food] = []
    seen: set[int] = set()
    for raw in names:
        name = (raw or "").strip()[:64]
        if not name:
            continue
        stmts = (
            # 1) 库名精确等于识别名
            select(Food)
            .where(Food.status == 1, Food.name == name)
            .order_by(Food.is_standard.desc(), Food.id)
            .limit(1),
            # 2) 别名精确（如「西红柿」命中「番茄」）
            select(Food)
            .join(FoodAlias, FoodAlias.food_id == Food.id)
            .where(Food.status == 1, FoodAlias.alias == name)
            .order_by(Food.is_standard.desc(), Food.id)
            .limit(1),
            # 3) 库菜名是识别名的子串（识别「清蒸鲈鱼」命中库「鲈鱼」）
            select(Food)
            .where(Food.status == 1, literal(name).contains(Food.name))
            .order_by(Food.is_standard.desc(), Food.id)
            .limit(1),
            # 4) 识别名是库菜名的子串（识别「排骨」命中库「红烧排骨」）
            select(Food)
            .where(Food.status == 1, Food.name.ilike(f"%{name}%"))
            .order_by(Food.is_standard.desc(), Food.id)
            .limit(1),
        )
        food = None
        for stmt in stmts:
            food = (await session.execute(stmt)).scalar_one_or_none()
            if food is not None:
                break
        if food is not None and int(food.id) not in seen:
            seen.add(int(food.id))
            matched.append(food)
    return matched


def build_combos_from_foods(foods: list[Food]) -> list[Combo]:
    """识别命中的食物 → 恰好 3 个组合（n=2 时 2 个）：按每 100g 热量升序连续切低/中/高三段。

    每菜固定 MATCH_PORTION_G 份量，热量按 compute_calories 逐项累加；
    按总热量升序输出（与标准库组合同序）。
    三段不重叠 → n≥3 必得 3 个不同组合（此前滑窗会因窗口重合去重后只剩 2 张）。
    """
    ordered = sorted(foods, key=lambda f: float(f.calories_100g))
    n = len(ordered)
    base, rem = divmod(n, 3)
    cut1 = base + (1 if rem else 0)
    cut2 = cut1 + base + (1 if rem > 1 else 0)
    windows = (
        ordered[:cut1],  # 最低卡
        ordered[cut1:cut2],  # 中段
        ordered[cut2:],  # 最高卡
    )
    stages = (
        ("清淡组合", "选了热量最低的几样，负担小"),
        ("均衡组合", "荤素搭配适中"),
        ("足量组合", "热量偏高，注意份量"),
    )
    combos: list[Combo] = []
    seen_names: set[str] = set()
    for i, group in enumerate(windows):
        if not group:
            continue
        name = " + ".join(food.name for food in group)
        if name in seen_names:
            continue
        seen_names.add(name)
        label, highlight = stages[i]
        template = ComboTemplate(label=label, highlight=highlight, slots=())
        items = tuple((food, MATCH_PORTION_G) for food in group)
        calories = round(
            sum(compute_calories(float(food.calories_100g), MATCH_PORTION_G) for food in group), 1
        )
        main = max(group, key=lambda f: float(f.protein_100g or 0))
        combos.append(
            Combo(
                template=template,
                items=items,
                calories=calories,
                name=name,
                food_id=int(main.id),
            )
        )
    combos.sort(key=lambda c: c.calories)
    return combos


# 主流程


async def recommend(
    session: AsyncSession,
    settings: Settings | None,
    user_id: int,
    meal_type: int,
    location: GeoLocation | None = None,
    budget: float | None = None,
    items: list[str] | None = None,
    llm_client: LLMClient | None = None,
) -> list[RecommendOption]:
    """饭点决策主流程：额度 → 候选 → LLM 结构化搭配 → 分级（AI 失败降级规则组合）。

    budget / location 现阶段无数据支撑（food 无价格列、商家域 Phase 3），只记录日志。
    items 为拍照/语音识别到的菜名（§5.2「菜单拍照识别+推荐」）：命中 ≥2 个食物时候选=识别
    菜单，否则候选=标准类目食物。LLM 结构化输出搭配 JSON（ids/grams/reason），后端按 id
    回查 DB 重算热量与等级；解析失败/超时/未配置 → 规则组合兜底，推荐永不报错。
    """
    s = settings or get_settings()
    if budget is not None or location is not None:
        logger.info("推荐收到预算/位置参数，Phase 3 才接入价格与商家，本轮忽略")

    allowance = await remaining_allowance(session, user_id, meal_type)

    # 候选池：识别菜名命中优先（≥2），否则标准类目候选；两条路径共用 LLM 结构化搭配
    matched: list[Food] = []
    if items:
        matched = await match_foods(session, items)
        if len(matched) < 2:
            matched = []
    candidates = matched if matched else await _standard_candidates(session)

    combos: list[Combo] = []
    bodies: list[str] | None = None
    if candidates:
        try:
            client = llm_client or llm_client_for(s)
            with ai_task("recommend"):
                structured = await structured_combos(
                    client, candidates, allowance, meal_type, budget, s.AI_TIMEOUT
                )
            if structured is not None:
                combos, bodies = structured
                logger.info("LLM 结构化搭配成功", extra={"combos": len(combos)})
        except Exception as exc:  # noqa: BLE001 - AI 不可用只降级，不阻断推荐
            logger.warning("LLM 结构化搭配失败，降级规则组合", extra={"reason": str(exc)})

    grades: list[Grade]
    if not combos:
        # 规则兜底：识别命中 → 低/中/高三段切法；否则标准库模板（行为与旧版一致）
        combos = build_combos_from_foods(matched) if matched else await build_combos(session)
        grades = [grade_for(combo.calories, allowance) for combo in combos]
        bodies = [rule_body(combo, grade) for combo, grade in zip(combos, grades, strict=True)]
    else:
        # 等级单一真源仍是后端数字：LLM 只出搭配与理由，等级由额度重算补前缀
        grades = [grade_for(combo.calories, allowance) for combo in combos]

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
