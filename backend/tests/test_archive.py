"""G8 记录按月分区归档测试（`app.tasks.archive.archive_old_records`）。

覆盖：3 年前的旧行迁入 `*_archive` 分区表、源表不再含旧行、近期行保留、
目标月份分区（不存在时动态创建）真实可用。

为何单开文件：归档任务为本轮 G8 新增，现有测试无归档/分区用例。
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text

from app.models import MealRecord, MealRecordArchive, User
from app.tasks.archive import archive_old_records


def _meal(user_id: int, created_at: datetime, name: str) -> MealRecord:
    return MealRecord(
        user_id=user_id,
        record_date=created_at.date(),
        meal_type=2,
        food_name_snapshot=name,
        amount_g=100,
        calories=100.0,
        source=3,
        created_at=created_at,
    )


async def test_archive_moves_old_rows_to_month_partition(db_session):
    """仅早于「2 年前」的行被迁入归档分区；近期行留在源表。"""
    user = User(openid=f"archive-{id(db_session)}", gender=1)
    db_session.add(user)
    await db_session.flush()

    now = datetime.now(timezone.utc)
    old_at = now - timedelta(days=365 * 3)
    old = _meal(user.id, old_at, "三年前的饭")
    recent = _meal(user.id, now, "今天的饭")
    db_session.add_all([old, recent])
    await db_session.commit()
    old_id, recent_id = old.id, recent.id

    counts = await archive_old_records(session=db_session)

    assert counts["meal_record"] == 1
    # 旧行进入归档分区表
    assert (
        await db_session.scalar(
            select(MealRecordArchive).where(MealRecordArchive.id == old_id)
        )
        is not None
    )
    # 源表不再含旧行，近期行保留
    assert await db_session.scalar(select(MealRecord).where(MealRecord.id == old_id)) is None
    assert (
        await db_session.scalar(select(MealRecord).where(MealRecord.id == recent_id)) is not None
    )
    # 目标月份分区真实存在（不存在时由任务动态 CREATE PARTITION）
    part = f"public.meal_record_archive_{old_at.strftime('%Y_%m')}"
    assert await db_session.scalar(text("SELECT to_regclass(:n)"), {"n": part}) is not None


async def test_archive_month_boundary_is_computed_on_pg_side(db_session):
    """月界必须由 PG 侧计算：跨 UTC/+08 月界的行落到其 +08 月份分区（`2023_10`）。

    固定 `created_at=2023-10-03T16:26:59Z`（+08 侧为 `2023-10-04 00:26`，跨 UTC 月界）。
    月界若改回 Python 侧 `.replace(day=1)`：`date_trunc('month', ...)` 的返回值经驱动归一到
    UTC 会退到 2023-09，建出的分区盖不住该行 → 整段 INSERT 报 `no partition of relation`。
    上一条用例用 `now - 3年`（随当天日期漂移），覆盖不到这一确定性边界。
    """
    user = User(openid=f"archive-tz-{id(db_session)}", gender=1)
    db_session.add(user)
    await db_session.flush()

    at = datetime.fromisoformat("2023-10-03T16:26:59+00:00")
    old = _meal(user.id, at, "跨月界的饭")
    db_session.add(old)
    await db_session.commit()
    old_id = old.id

    counts = await archive_old_records(session=db_session)

    assert counts["meal_record"] == 1
    # 落在 2023-10 分区（而非被 UTC 归一后的 2023-09）
    part = "public.meal_record_archive_2023_10"
    assert await db_session.scalar(text("SELECT to_regclass(:n)"), {"n": part}) is not None
    assert await db_session.scalar(select(MealRecord).where(MealRecord.id == old_id)) is None
    assert (
        await db_session.scalar(
            select(MealRecordArchive).where(MealRecordArchive.id == old_id)
        )
        is not None
    )
