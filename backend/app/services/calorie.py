"""热量引擎（纯函数，无 DB 依赖）：BMR / PAL / NEAT / EAT / TEF / TEE / 缺口 + 步数校准。

真源与口径：
- BMR：Mifflin-St Jeor（04 文档 §6.3.1）。
- 预算 = BMR × PAL；TEE = BMR×PAL + EAT + TEF，TEF = 摄入×10%（04 §6.3.1）。
- 缺口 = 摄入 − TEE（负值为热量缺口）。
- NEAT 校准（04 §6.3.3）：基础 NEAT = MET_state × 体重 × 非睡眠小时；
  逐时步频映射 MET（散步 2.5 / 快走 4.3 / 跑步 8.0），累加得 NEAT_steps，
  与状态法加权（步数 0.6 / 状态 0.4）。
  NEAT 为「非睡眠时段总消耗」（MET 含基础代谢），仅作展示与校准量，不叠加进 TEE。

【默认决策】（docs/split/10 零提问默认决策规则，文档未给出的常量取业界常见值）：
- PAL 表：1卧床 1.2 / 2久坐 1.4 / 3轻度 1.6 / 4中度 1.8 / 5高度 2.0；
- MET_state 表：1.0 / 1.2 / 1.5 / 1.8 / 2.2（与活动水平 1~5 对应）；
- 未填出生年份：age 默认 30；未填活动水平：默认 2（久坐，PAL 1.4）；
- 非睡眠小时 NON_SLEEP_HOURS = 16；逐时步频分档阈值见 `_met_by_cadence`。
- 步数=0 用 PAL 估算（calibration_used=False）；步数>0 走校准（calibration_used=True）。

环形图「还能吃」口径（01 文档 §2.5 / plan.md §7 退出标准，误差 0 对拍）：
    today_left = BMR×PAL − 摄入 + 运动消耗 − TEF
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

# ---- 常量表（默认决策）----

PAL_BY_LEVEL: dict[int, float] = {1: 1.2, 2: 1.4, 3: 1.6, 4: 1.8, 5: 2.0}
MET_STATE_BY_LEVEL: dict[int, float] = {1: 1.0, 2: 1.2, 3: 1.5, 4: 1.8, 5: 2.2}

DEFAULT_ACTIVITY_LEVEL = 2
DEFAULT_AGE = 30
NON_SLEEP_HOURS = 16.0
TEF_RATE = 0.10

# 步数校准 MET 档（04 §6.3.3）
MET_WALK = 2.5  # 散步
MET_BRISK = 4.3  # 快走
MET_RUN = 8.0  # 跑步
MET_SIT = 1.0  # 静坐

STEP_WEIGHT = 0.6  # 步数占比
STATE_WEIGHT = 0.4  # 状态占比


def pal_for_level(level: int | None) -> float:
    return PAL_BY_LEVEL.get(level or DEFAULT_ACTIVITY_LEVEL, PAL_BY_LEVEL[DEFAULT_ACTIVITY_LEVEL])


def met_state_for_level(level: int | None) -> float:
    return MET_STATE_BY_LEVEL.get(
        level or DEFAULT_ACTIVITY_LEVEL, MET_STATE_BY_LEVEL[DEFAULT_ACTIVITY_LEVEL]
    )


def age_from_birth_year(birth_year: int | None, today: date | None = None) -> int:
    """出生年份 → 年龄；缺失/异常（<=0 或 >120）回退默认 30。"""
    ref = today or date.today()
    if not birth_year:
        return DEFAULT_AGE
    age = ref.year - int(birth_year)
    if age <= 0 or age > 120:
        return DEFAULT_AGE
    return age


def bmr_mifflin_st_jeor(*, gender: int, weight_kg: float, height_cm: float, age: int) -> float:
    """Mifflin-St Jeor：男 +5 / 女 −161。返回 kcal。"""
    base = 10.0 * weight_kg + 6.25 * height_cm - 5.0 * age
    return round(base + (5.0 if gender == 1 else -161.0), 1)


def state_neat(*, weight_kg: float, activity_level: int | None) -> float:
    """状态法 NEAT = MET_state × 体重 × 非睡眠小时。"""
    return round(met_state_for_level(activity_level) * weight_kg * NON_SLEEP_HOURS, 1)


def _met_by_cadence(steps_per_hour: float) -> float:
    """每小时步频 → MET（默认决策：文档只给散步/快走/跑步三档）。"""
    if steps_per_hour >= 2000:
        return MET_RUN
    if steps_per_hour >= 1000:
        return MET_BRISK
    if steps_per_hour >= 100:
        return MET_WALK
    return MET_SIT


def steps_neat(*, weight_kg: float, steps: int, hourly: dict | None) -> float:
    """步数法 NEAT。

    有逐时数据：Σ( MET_hour × 体重 × 1h )（键为 0-23 小时字符串/整数）。
    无逐时数据：按全天步数均摊到非睡眠小时得平均步频，再 × MET × 非睡眠小时。
    """
    if hourly:
        total = 0.0
        for _hour, cnt in hourly.items():
            try:
                n = float(cnt)
            except (TypeError, ValueError):
                continue
            total += _met_by_cadence(n) * weight_kg * 1.0
        return round(total, 1)
    avg_cadence = (steps or 0) / NON_SLEEP_HOURS
    return round(_met_by_cadence(avg_cadence) * weight_kg * NON_SLEEP_HOURS, 1)


def calibrate_neat(
    *, weight_kg: float, activity_level: int | None, steps: int, hourly: dict | None = None
) -> tuple[float, bool]:
    """返回 (NEAT, calibration_used)。

    步数<=0：状态法估算，未校准；步数>0：步数 0.6 + 状态 0.4 加权，已校准。
    """
    state = state_neat(weight_kg=weight_kg, activity_level=activity_level)
    if not steps or steps <= 0:
        return state, False
    step_val = steps_neat(weight_kg=weight_kg, steps=steps, hourly=hourly)
    return round(STEP_WEIGHT * step_val + STATE_WEIGHT * state, 1), True


@dataclass
class CalorieInputs:
    """一次热量账户计算的输入（均为当日口径）。"""

    gender: int
    weight_kg: float
    height_cm: float
    age: int
    activity_level: int
    intake: float = 0.0  # 当日摄入 kcal
    eat: float = 0.0  # 当日运动消耗 kcal
    steps: int = 0
    hourly: dict | None = None


@dataclass
class CalorieResult:
    bmr: float
    pal: float
    neat: float
    eat: float
    tef: float
    tee: float
    intake: float
    deficit: float
    steps: int
    calories_burnt: float
    calibration_used: bool
    today_left: float


def compute_account(inp: CalorieInputs) -> CalorieResult:
    """热量账户核心计算（口径见模块 docstring）。"""
    bmr = bmr_mifflin_st_jeor(
        gender=inp.gender, weight_kg=inp.weight_kg, height_cm=inp.height_cm, age=inp.age
    )
    pal = pal_for_level(inp.activity_level)
    budget = bmr * pal
    neat, calibration_used = calibrate_neat(
        weight_kg=inp.weight_kg,
        activity_level=inp.activity_level,
        steps=inp.steps,
        hourly=inp.hourly,
    )
    intake = round(float(inp.intake or 0.0), 1)
    eat = round(float(inp.eat or 0.0), 1)
    tef = round(intake * TEF_RATE, 1)
    # TEE 恒按 04 §6.3.1：TEE = BMR×PAL + EAT + TEF。
    # NEAT 为「非睡眠时段总消耗」展示/校准量（含基础代谢），不叠加进 TEE，避免重复计基础代谢。
    tee = round(budget + eat + tef, 1)
    deficit = round(intake - tee, 1)
    # 环形图「还能吃」：01 §2.5 / plan.md §7 退出标准口径
    today_left = round(budget - intake + eat - tef, 1)
    return CalorieResult(
        bmr=bmr,
        pal=pal,
        neat=neat,
        eat=eat,
        tef=tef,
        tee=tee,
        intake=intake,
        deficit=deficit,
        steps=int(inp.steps or 0),
        calories_burnt=eat,
        calibration_used=calibration_used,
        today_left=today_left,
    )
