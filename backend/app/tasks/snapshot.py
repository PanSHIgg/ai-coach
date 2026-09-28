"""每日热量快照生成任务（04 §6.3.1：每天 0 点生成 daily_snapshot）。

职责：对「当天有记录或已建档」的用户，幂等生成当日 daily_snapshot（复用
`account.upsert_snapshot`，PG ON CONFLICT 保证重复执行不新增）。

【假设】调度方式（10 默认决策，二选一，均不阻塞本任务发布）：
- Redis Streams：`enqueue_daily_snapshot` 投递到 `SNAPSHOT_STREAM`，由常驻消费者触发；
- APScheduler/系统 cron：直接调用 `generate_daily_snapshots`（本函数无外部依赖）。
Redis 不可用时投递环节优雅降级返回 False，回退到手动/定时直调，不抛异常。

CLI（便于验证/补跑）：
    python -m app.tasks.snapshot --once            # 立即为今天生成一次
    python -m app.tasks.snapshot --once --date 2026-09-27
    python -m app.tasks.snapshot --enqueue         # 仅投递到 Redis Stream
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.session import get_sessionmaker
from app.models import BodyProfile, MealRecord, SportRecord, StepRecord
from app.services import account

TZ = timezone(timedelta(hours=8))
SNAPSHOT_STREAM = "ai_coach:snapshot:jobs"

logger = get_logger(__name__)


def _today() -> date:
    return datetime.now(TZ).date()


async def _target_user_ids(session: AsyncSession, day: date) -> list[int]:
    """当天有记录或已建档的用户 id 去重集合（行级隔离由调用方负责）。"""
    ids: set[int] = set()

    profile_ids = (await session.scalars(select(BodyProfile.user_id))).all()
    ids.update(int(i) for i in profile_ids if i is not None)

    meal_ids = (
        await session.scalars(
            select(MealRecord.user_id)
            .where(MealRecord.record_date == day, MealRecord.user_id.is_not(None))
            .distinct()
        )
    ).all()
    ids.update(int(i) for i in meal_ids if i is not None)

    step_ids = (
        await session.scalars(
            select(StepRecord.user_id)
            .where(StepRecord.record_date == day, StepRecord.user_id.is_not(None))
            .distinct()
        )
    ).all()
    ids.update(int(i) for i in step_ids if i is not None)

    start = datetime.combine(day, time.min, tzinfo=TZ)
    end = start + timedelta(days=1)
    sport_ids = (
        await session.scalars(
            select(SportRecord.user_id)
            .where(
                SportRecord.record_at >= start,
                SportRecord.record_at < end,
                SportRecord.user_id.is_not(None),
            )
            .distinct()
        )
    ).all()
    ids.update(int(i) for i in sport_ids if i is not None)

    return sorted(ids)


async def generate_daily_snapshots(
    day: date | None = None, session: AsyncSession | None = None
) -> int:
    """为「当天有记录或已建档」的用户幂等生成快照，返回成功写入的用户数。

    任何异常都在任务内消化（记日志 + 回滚），绝不向调度器抛出。
    """
    day = day or _today()
    own_session = session is None
    if own_session:
        session = get_sessionmaker()()

    count = 0
    try:
        user_ids = await _target_user_ids(session, day)
        for user_id in user_ids:
            try:
                await account.upsert_snapshot(session, user_id, day)
                count += 1
            except Exception as exc:  # noqa: BLE001 - 单用户失败不影响其余用户
                await session.rollback()
                logger.warning(
                    "快照生成失败，已跳过该用户",
                    extra={"user_id": user_id, "date": day.isoformat(), "reason": str(exc)},
                )
    except Exception as exc:  # noqa: BLE001 - 整体失败也不抛给调度器
        logger.warning(
            "快照任务执行失败，已降级", extra={"date": day.isoformat(), "reason": str(exc)}
        )
    finally:
        if own_session:
            await session.close()

    logger.info("快照任务完成", extra={"date": day.isoformat(), "users": count})
    return count


async def enqueue_daily_snapshot(day: date | None = None) -> bool:
    """把一次快照任务投递到 Redis Stream；Redis 不可用时降级返回 False（不抛）。"""
    from app.db.redis import get_redis

    client = await get_redis()
    if client is None:
        logger.warning("Redis 不可用，快照任务投递跳过（请走 --once 或定时直调）")
        return False
    try:
        await client.xadd(SNAPSHOT_STREAM, {"date": (day or _today()).isoformat()})
        return True
    except Exception as exc:  # noqa: BLE001 - 投递失败一律降级
        logger.warning("快照任务投递失败，已降级", extra={"reason": str(exc)})
        return False


def main(argv: list[str] | None = None) -> int:
    """CLI 入口：--once 立即执行；--enqueue 仅投递 Stream。"""
    parser = argparse.ArgumentParser(description="每日热量快照生成任务")
    parser.add_argument("--once", action="store_true", help="立即执行一次快照生成")
    parser.add_argument(
        "--enqueue", action="store_true", help="仅投递到 Redis Stream（供调度消费）"
    )
    parser.add_argument(
        "--date", type=date.fromisoformat, default=None, help="目标日期 YYYY-MM-DD（默认今天）"
    )
    args = parser.parse_args(argv)

    if args.enqueue and not args.once:
        delivered = asyncio.run(enqueue_daily_snapshot(args.date))
        print("已投递到 Redis Stream" if delivered else "Redis 不可用，投递跳过（可改用 --once）")
        return 0

    users = asyncio.run(generate_daily_snapshots(day=args.date))
    print(f"快照生成完成：{users} 个用户")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
