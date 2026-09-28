"""步数同步服务（BE2b）：写 step_record（幂等）+ NEAT 校准 + 触发当日快照重算。

口径（04 §6.3.3）：
- NEAT_calibrated、calibration_used 由 `calorie.calibrate_neat` 给出：
  步数<=0 → 状态法（未校准）；步数>0 → 步数 0.6 + 状态 0.4 加权（已校准）。
- 逐时步频→MET 映射复用 `calorie`（散步 2.5 / 快走 4.3 / 跑步 8.0）。
- `met`（落 step_record.calibrated_met）【假设】= NEAT_calibrated / (体重 × 非睡眠小时)，
  即加权后的等效 MET；步数=0 时退化为状态法 MET（MET_state）。
- `delta_calories` = NEAT_calibrated − 状态法 NEAT（校准带来的额外消耗，步数=0 时为 0）。
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppException
from app.models import StepRecord
from app.schemas.common import ErrorCode
from app.schemas.record import StepsSyncData
from app.services import account, calorie


async def _require_weight(session: AsyncSession, user_id: int) -> tuple[float, int]:
    """取建档体重与活动水平；未建档/体重非法抛 3001（与账户服务一致）。"""
    profile = await account.get_body_profile(session, user_id)
    weight = float(profile.current_weight) if profile and profile.current_weight else 0.0
    if profile is None or weight <= 0:
        raise AppException(ErrorCode.NOT_FOUND, "尚未创建身体档案")
    return weight, int(profile.activity_level or calorie.DEFAULT_ACTIVITY_LEVEL)


async def _upsert_step_record(
    session: AsyncSession,
    user_id: int,
    day: date,
    steps: int,
    hourly: dict | None,
    met: float,
) -> None:
    """(user_id, record_date) 幂等 upsert；重复同步同一天只更新不新增。"""
    values = {
        "user_id": user_id,
        "record_date": day,
        "steps": steps,
        "hourly_json": hourly or {},
        "calibrated_met": met,
    }
    stmt = pg_insert(StepRecord).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id", "record_date"],
        set_={"steps": steps, "hourly_json": hourly or {}, "calibrated_met": met},
    )
    await session.execute(stmt)
    await session.commit()


async def sync_steps(
    session: AsyncSession,
    user_id: int,
    day: date,
    steps: int,
    hourly: dict | None = None,
) -> StepsSyncData:
    """落库步数 → 校准 NEAT → 重算当日快照，返回校准结果。"""
    weight, level = await _require_weight(session, user_id)

    neat, _used = calorie.calibrate_neat(
        weight_kg=weight, activity_level=level, steps=steps, hourly=hourly
    )
    state = calorie.state_neat(weight_kg=weight, activity_level=level)
    # 加权后等效 MET（见模块 docstring【假设】）
    met = round(neat / (weight * calorie.NON_SLEEP_HOURS), 2)

    await _upsert_step_record(session, user_id, day, steps, hourly, met)
    # 步数变化影响 NEAT/校准标记 → 重算当日快照（幂等）
    await account.recompute_day(session, user_id, day)

    return StepsSyncData(
        neat_calibrated=neat,
        met=met,
        delta_calories=round(neat - state, 1),
    )
