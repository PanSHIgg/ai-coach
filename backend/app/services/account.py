"""热量账户服务：读当日记录 → 走热量引擎 → 幂等写 daily_snapshot → 产出账户/趋势。

- 快照唯一约束 (user_id, snapshot_date)：PG `INSERT ... ON CONFLICT DO UPDATE` 幂等。
- 写入触发：饮食/运动/步数写操作后调用 `recompute_day` 重算当日。
- 时区：业务口径 UTC+8（Asia/Shanghai），运动记录按 +08:00 日界聚合。
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppException
from app.models import BodyProfile, DailySnapshot, MealRecord, SportRecord, StepRecord
from app.schemas.account import AccountTrendData, DailyAccount, DailyTrendItem, MealSummary
from app.schemas.common import ErrorCode
from app.services import calorie

TZ = timezone(timedelta(hours=8))
MEAL_LABELS = {1: "早餐", 2: "午餐", 3: "晚餐", 4: "加餐"}
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


async def compute_result(session: AsyncSession, user_id: int, day: date) -> calorie.CalorieResult:
    """读当日数据 → 热量引擎结果。未建档抛 3001。"""
    profile = await get_body_profile(session, user_id)
    if profile is None:
        raise AppException(ErrorCode.NOT_FOUND, "尚未创建身体档案")
    weight = float(profile.current_weight or 0)
    if weight <= 0:
        raise AppException(ErrorCode.NOT_FOUND, "尚未创建身体档案")
    step_row = await _day_steps(session, user_id, day)
    steps = int(step_row.steps) if step_row else 0
    hourly = step_row.hourly_json if step_row else None
    return calorie.compute_account(
        calorie.CalorieInputs(
            gender=int(profile.gender),
            weight_kg=weight,
            height_cm=float(profile.height_cm),
            age=int(profile.age or calorie.age_from_birth_year(profile.birth_year, day)),
            activity_level=int(profile.activity_level or calorie.DEFAULT_ACTIVITY_LEVEL),
            intake=await _day_intake(session, user_id, day),
            eat=await _day_eat(session, user_id, day),
            steps=steps,
            hourly=hourly,
        )
    )


async def upsert_snapshot(
    session: AsyncSession, user_id: int, day: date, result: calorie.CalorieResult | None = None
) -> calorie.CalorieResult:
    """幂等写当日快照（(user_id, snapshot_date) 冲突则更新）。返回计算结果。

    写库前校验当日合计：intake/eat/tee 任一超 NUMERIC(7,1) 上限 → 2001（防写库溢出 500）。
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
    stmt = pg_insert(DailySnapshot).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id", "snapshot_date"],
        set_={f: getattr(res, f) for f in _ACCOUNT_FIELDS},
    )
    await session.execute(stmt)
    await session.commit()
    return res


async def recompute_day(session: AsyncSession, user_id: int, day: date | None = None) -> None:
    """记录写操作后重算当日快照（供 BE3/BE2b 调用）。"""
    await upsert_snapshot(session, user_id, day or datetime.now(TZ).date())


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


async def get_today(session: AsyncSession, user_id: int) -> DailyAccount:
    """今日账户：确保快照最新（幂等重算），返回 DailyAccount。"""
    day = datetime.now(TZ).date()
    res = await upsert_snapshot(session, user_id, day)
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
        meals=await _meals_summary(session, user_id, day),
    )


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
