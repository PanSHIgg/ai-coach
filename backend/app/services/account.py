"""热量账户服务：读当日记录 → 走热量引擎 → 幂等写 daily_snapshot → 产出账户/趋势。

- 快照唯一约束 (user_id, snapshot_date)：PG `INSERT ... ON CONFLICT DO UPDATE` 幂等。
- 写入触发：饮食/运动/步数写操作后调用 `recompute_day` 重算当日。
- 时区：业务口径 UTC+8（Asia/Shanghai），运动记录按 +08:00 日界聚合。
- 当日状态（F-01，§2.3.1/§6.3.3）：`daily_snapshot.activity_level` 存当日所选状态；
  已选则 PAL/NEAT 取当日状态，未选回退建档 `body_profile.activity_level`（「不点则用默认 PAL」）。
  不改变 TEE 结构（TEE = BMR×PAL + EAT + TEF）。
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppException
from app.models import (
    BodyProfile,
    DailySnapshot,
    MealRecord,
    SportRecord,
    StepRecord,
    WeightRecord,
)
from app.schemas.account import AccountTrendData, DailyAccount, DailyTrendItem, MealSummary
from app.schemas.common import ErrorCode
from app.services import calorie

TZ = timezone(timedelta(hours=8))
MEAL_LABELS = {1: "早餐", 2: "午餐", 3: "晚餐", 4: "加餐"}
# 第四层「体重变化·周度反推」校准窗口【假设】：近 7 天
WEEK_CALIBRATION_DAYS = 7
# daily_snapshot.intake/eat/tee 为 NUMERIC(7,1)，上限 999999.9；当日合计越界前置 2001，
# 避免「多条记录叠加」把快照列写溢出（→ HTTP 500）。deficit 为 NUMERIC(8,1) 无需校验。
SNAPSHOT_NUMERIC_MAX = 999999.9

_ACCOUNT_FIELDS = (
    "bmr",
    "pal",
    "neat",
    "eat",
    "tef",
    "tee",
    "intake",
    "deficit",
    "steps",
    "calories_burnt",
    "calibration_used",
)


async def get_body_profile(session: AsyncSession, user_id: int) -> BodyProfile | None:
    return (
        await session.execute(select(BodyProfile).where(BodyProfile.user_id == user_id))
    ).scalar_one_or_none()


async def _day_intake(session: AsyncSession, user_id: int, day: date) -> float:
    total = await session.scalar(
        select(func.coalesce(func.sum(MealRecord.calories), 0)).where(
            MealRecord.user_id == user_id, MealRecord.record_date == day
        )
    )
    return float(total or 0)


async def _day_eat(session: AsyncSession, user_id: int, day: date) -> float:
    start = datetime.combine(day, time.min, tzinfo=TZ)
    end = start + timedelta(days=1)
    total = await session.scalar(
        select(func.coalesce(func.sum(SportRecord.calories), 0)).where(
            SportRecord.user_id == user_id,
            SportRecord.record_at >= start,
            SportRecord.record_at < end,
        )
    )
    return float(total or 0)


async def _day_steps(session: AsyncSession, user_id: int, day: date) -> StepRecord | None:
    return (
        await session.execute(
            select(StepRecord).where(StepRecord.user_id == user_id, StepRecord.record_date == day)
        )
    ).scalar_one_or_none()


async def _selected_status_level(session: AsyncSession, user_id: int, day: date) -> int | None:
    """当日已选状态（daily_snapshot.activity_level）；未选/无快照返回 None。"""
    value = await session.scalar(
        select(DailySnapshot.activity_level).where(
            DailySnapshot.user_id == user_id, DailySnapshot.snapshot_date == day
        )
    )
    return int(value) if value is not None else None


async def compute_result(
    session: AsyncSession,
    user_id: int,
    day: date,
    *,
    activity_level: int | None = None,
) -> calorie.CalorieResult:
    """读当日数据 → 热量引擎结果。未建档抛 3001。

    活动水平：显式传入（写入当日状态）时直接采用；否则取当日已选状态，未选回退建档
    `body_profile.activity_level`（F-01「不点则用默认 PAL」）。
    """
    profile = await get_body_profile(session, user_id)
    if profile is None:
        raise AppException(ErrorCode.NOT_FOUND, "尚未创建身体档案")
    weight = float(profile.current_weight or 0)
    if weight <= 0:
        raise AppException(ErrorCode.NOT_FOUND, "尚未创建身体档案")
    if activity_level is None:
        selected = await _selected_status_level(session, user_id, day)
        activity_level = (
            selected
            if selected is not None
            else int(profile.activity_level or calorie.DEFAULT_ACTIVITY_LEVEL)
        )
    step_row = await _day_steps(session, user_id, day)
    steps = int(step_row.steps) if step_row else 0
    hourly = step_row.hourly_json if step_row else None
    return calorie.compute_account(
        calorie.CalorieInputs(
            gender=int(profile.gender),
            weight_kg=weight,
            height_cm=float(profile.height_cm),
            age=int(profile.age or calorie.age_from_birth_year(profile.birth_year, day)),
            activity_level=int(activity_level),
            intake=await _day_intake(session, user_id, day),
            eat=await _day_eat(session, user_id, day),
            steps=steps,
            hourly=hourly,
        )
    )


async def upsert_snapshot(
    session: AsyncSession,
    user_id: int,
    day: date,
    result: calorie.CalorieResult | None = None,
    *,
    activity_level: int | None = None,
) -> calorie.CalorieResult:
    """幂等写当日快照（(user_id, snapshot_date) 冲突则更新）。返回计算结果。

    写库前校验当日合计：intake/eat/tee 任一超 NUMERIC(7,1) 上限 → 2001（防写库溢出 500）。
    `activity_level` 仅在「写入当日状态」（set_today_status）时传入；普通重算不传，
    避免把用户已选状态覆盖为 NULL（ON CONFLICT 只更新 _ACCOUNT_FIELDS）。
    """
    res = result or await compute_result(session, user_id, day)
    for value in (res.intake, res.eat, res.tee):
        if float(value) > SNAPSHOT_NUMERIC_MAX:
            raise AppException(ErrorCode.VALIDATION_ERROR, "当日数据超出合理范围")
    values = {
        "user_id": user_id,
        "snapshot_date": day,
        **{f: getattr(res, f) for f in _ACCOUNT_FIELDS},
    }
    set_fields = {f: getattr(res, f) for f in _ACCOUNT_FIELDS}
    if activity_level is not None:
        values["activity_level"] = activity_level
        set_fields["activity_level"] = activity_level
    stmt = pg_insert(DailySnapshot).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id", "snapshot_date"],
        set_=set_fields,
    )
    await session.execute(stmt)
    await session.commit()
    return res


async def recompute_day(session: AsyncSession, user_id: int, day: date | None = None) -> None:
    """记录写操作后重算当日快照（供 BE3/BE2b 调用）。"""
    await upsert_snapshot(session, user_id, day or datetime.now(TZ).date())


async def get_weekly_calibration(session: AsyncSession, user_id: int) -> calorie.WeeklyCalibration:
    """NEAT 第四层「体重变化·周度反推」校准（F-07，04 §6.3.3）。

    周度口径：近 `WEEK_CALIBRATION_DAYS` 天「实际体重变化」vs「快照累计缺口对应的
    体重变化」，经 `calorie.weekly_neat_calibration` 反推有界 PAL/NEAT 修正系数。
    仅服务周度校准路径；日内计算（compute_result/get_today）不接入，保证不回归。
    数据不足（无档案/最近窗口体重记录 < 2 条/无快照）→ 偏差按 0，系数 1.0（不校准）。
    """
    today = datetime.now(TZ).date()
    start = today - timedelta(days=WEEK_CALIBRATION_DAYS - 1)
    weights = (
        (
            await session.execute(
                select(WeightRecord)
                .where(
                    WeightRecord.user_id == user_id,
                    WeightRecord.record_at >= start,
                    WeightRecord.record_at <= today,
                )
                .order_by(WeightRecord.record_at.asc(), WeightRecord.id.asc())
            )
        )
        .scalars()
        .all()
    )
    actual_change = (
        round(float(weights[-1].weight) - float(weights[0].weight), 3) if len(weights) >= 2 else 0.0
    )
    deficit_sum = float(
        await session.scalar(
            select(func.coalesce(func.sum(DailySnapshot.deficit), 0)).where(
                DailySnapshot.user_id == user_id,
                DailySnapshot.snapshot_date >= start,
                DailySnapshot.snapshot_date <= today,
            )
        )
        or 0
    )
    return calorie.weekly_neat_calibration(
        actual_change_kg=actual_change, predicted_deficit_kcal=deficit_sum
    )


async def _meals_summary(session: AsyncSession, user_id: int, day: date) -> list[MealSummary]:
    rows = (
        await session.execute(
            select(
                MealRecord.meal_type,
                func.coalesce(func.sum(MealRecord.calories), 0).label("kcal"),
            )
            .where(MealRecord.user_id == user_id, MealRecord.record_date == day)
            .group_by(MealRecord.meal_type)
            .order_by(MealRecord.meal_type)
        )
    ).all()
    return [
        MealSummary(
            meal_type=int(r.meal_type),
            name=MEAL_LABELS.get(int(r.meal_type), "加餐"),
            calories=round(float(r.kcal), 1),
        )
        for r in rows
    ]


async def _daily_account(
    session: AsyncSession,
    user_id: int,
    day: date,
    res: calorie.CalorieResult,
    activity_level: int | None,
) -> DailyAccount:
    """由引擎结果组装 DailyAccount（含当日已选状态与摄入明细）。"""
    return DailyAccount(
        date=day,
        bmr=res.bmr,
        pal=res.pal,
        neat=res.neat,
        eat=res.eat,
        tef=res.tef,
        tee=res.tee,
        intake=res.intake,
        deficit=res.deficit,
        steps=res.steps,
        calories_burnt=res.calories_burnt,
        calibration_used=res.calibration_used,
        today_left=res.today_left,
        activity_level=activity_level,
        meals=await _meals_summary(session, user_id, day),
    )


async def get_today(session: AsyncSession, user_id: int) -> DailyAccount:
    """今日账户：确保快照最新（幂等重算），返回 DailyAccount（含当日已选状态）。"""
    day = datetime.now(TZ).date()
    res = await upsert_snapshot(session, user_id, day)
    return await _daily_account(
        session, user_id, day, res, await _selected_status_level(session, user_id, day)
    )


async def set_today_status(
    session: AsyncSession, user_id: int, activity_level: int
) -> DailyAccount:
    """写入当日所选状态并重算当日快照（F-01，§2.3.1「今天什么状态」/§6.3.3 第一层粗调）。

    状态落 `daily_snapshot.activity_level`；当日 PAL/NEAT 即时按该状态取值（不改 TEE 结构），
    之后任意重算（饮食/运动写操作）仍读该列，未选则回退建档 activity_level。未建档抛 3001。
    """
    day = datetime.now(TZ).date()
    res = await compute_result(session, user_id, day, activity_level=activity_level)
    await upsert_snapshot(session, user_id, day, res, activity_level=activity_level)
    return await _daily_account(session, user_id, day, res, activity_level)


async def get_trend(
    session: AsyncSession, user_id: int, start: date | None, end: date | None
) -> AccountTrendData:
    """按日趋势：【假设】缺省最近 7 天；返回已有快照（无快照的日期不造数）。"""
    today = datetime.now(TZ).date()
    end = end or today
    start = start or (end - timedelta(days=6))
    rows = (
        (
            await session.execute(
                select(DailySnapshot)
                .where(
                    DailySnapshot.user_id == user_id,
                    DailySnapshot.snapshot_date >= start,
                    DailySnapshot.snapshot_date <= end,
                )
                .order_by(DailySnapshot.snapshot_date)
            )
        )
        .scalars()
        .all()
    )
    return AccountTrendData(
        items=[
            DailyTrendItem(
                date=r.snapshot_date,
                intake=float(r.intake or 0),
                tee=float(r.tee or 0),
                deficit=float(r.deficit or 0),
                steps=int(r.steps or 0),
                calories_burnt=float(r.calories_burnt or 0),
            )
            for r in rows
        ]
    )
