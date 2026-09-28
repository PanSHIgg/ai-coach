"""提醒订阅服务（BE-n）：订阅设置 upsert + 餐前/深夜提醒调度入口。

- 订阅：(user_id, template_type) 唯一；订阅幂等 upsert（status=1、subscribe_count+1、
  last_subscribe_at=now）；取消置 status=0（保留累计次数）。
- 调度：`enqueue_due_reminders` 为最小可运行实现——到点把待发提醒投入 Redis Stream
  `notification:reminders`；Redis 不可用时优雅降级（仅记录待发列表、不抛异常）。
- 默认决策：提醒窗口 template_type 1午餐 11:00 / 2晚餐 17:00 / 3深夜防崩塌 22:30
  （04 §6.3 / notification schema 注释），命中窗口 ±30 分钟内视为到点。
"""

from __future__ import annotations

import json
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.redis import get_redis
from app.models import Subscription
from app.schemas.notification import SubscriptionData, SubscriptionItem, SubscriptionOut

logger = get_logger(__name__)

TZ = timezone(timedelta(hours=8))
REMINDER_WINDOW = timedelta(minutes=30)  # 到点判定窗口
REMINDER_STREAM_KEY = "notification:reminders"

# template_type → 提醒时刻（默认决策，schema 注释口径）
REMINDER_SCHEDULE: dict[int, time] = {
    1: time(11, 0),  # 午餐提醒
    2: time(17, 0),  # 晚餐提醒
    3: time(22, 30),  # 深夜防崩塌
    4: time(8, 0),  # 称重提醒（晨起）
}


def _to_out(row: Subscription) -> SubscriptionOut:
    return SubscriptionOut(
        template_type=int(row.template_type),
        status=int(row.status),
        subscribe_count=int(row.subscribe_count or 0),
        last_subscribe_at=row.last_subscribe_at,
    )


def _to_item(row: Subscription) -> SubscriptionItem:
    return SubscriptionItem(
        template_type=int(row.template_type),
        status=int(row.status),
        subscribe_count=int(row.subscribe_count or 0),
        last_subscribe_at=row.last_subscribe_at,
    )


async def list_subscriptions(session: AsyncSession, user_id: int) -> SubscriptionData:
    """当前用户订阅列表（行级隔离）。"""
    rows = (
        (
            await session.execute(
                select(Subscription)
                .where(Subscription.user_id == user_id)
                .order_by(Subscription.template_type)
            )
        )
        .scalars()
        .all()
    )
    return SubscriptionData(items=[_to_item(r) for r in rows])


async def subscribe(session: AsyncSession, user_id: int, template_type: int) -> SubscriptionOut:
    """幂等订阅：(user_id, template_type) 冲突则 status=1、次数+1、刷新时间。"""
    stmt = pg_insert(Subscription).values(
        user_id=user_id,
        template_type=template_type,
        status=1,
        subscribe_count=1,
        last_subscribe_at=datetime.now(TZ),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id", "template_type"],
        set_={
            "status": 1,
            "subscribe_count": Subscription.subscribe_count + 1,
            "last_subscribe_at": datetime.now(TZ),
            "updated_at": datetime.now(TZ),
        },
    )
    await session.execute(stmt)
    await session.commit()
    row = (
        await session.execute(
            select(Subscription).where(
                Subscription.user_id == user_id, Subscription.template_type == template_type
            )
        )
    ).scalar_one()
    return _to_out(row)


async def cancel_subscription(
    session: AsyncSession, user_id: int, template_type: int
) -> SubscriptionOut:
    """取消订阅：status=0（保留 subscribe_count 累计）；无记录则建一条 status=0。"""
    stmt = pg_insert(Subscription).values(
        user_id=user_id, template_type=template_type, status=0, subscribe_count=0
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id", "template_type"],
        set_={"status": 0, "updated_at": datetime.now(TZ)},
    )
    await session.execute(stmt)
    await session.commit()
    row = (
        await session.execute(
            select(Subscription).where(
                Subscription.user_id == user_id, Subscription.template_type == template_type
            )
        )
    ).scalar_one()
    return _to_out(row)


def _due_template_types(at: datetime) -> list[int]:
    """当前时刻命中的提醒类型（±30 分钟窗口）。"""
    now_minutes = at.hour * 60 + at.minute
    due: list[int] = []
    for template_type, at_time in REMINDER_SCHEDULE.items():
        scheduled = at_time.hour * 60 + at_time.minute
        if abs(now_minutes - scheduled) <= REMINDER_WINDOW.total_seconds() // 60:
            due.append(template_type)
    return due


async def enqueue_due_reminders(session: AsyncSession, at: datetime | None = None) -> list[dict]:
    """调度入口：把到点且已订阅的提醒投入 Redis Stream；Redis 不可用则降级返回待发列表。"""
    now = at or datetime.now(TZ)
    due = _due_template_types(now)
    if not due:
        return []
    rows = (
        (
            await session.execute(
                select(Subscription).where(
                    Subscription.user_id.is_not(None),
                    Subscription.template_type.in_(due),
                    Subscription.status == 1,
                )
            )
        )
        .scalars()
        .all()
    )
    payloads = [
        {"user_id": int(r.user_id), "template_type": int(r.template_type), "at": now.isoformat()}
        for r in rows
    ]
    if not payloads:
        return []
    redis = await get_redis()
    if redis is None:
        # 优雅降级：不阻断、不抛错，仅记录待发列表待后续补发
        logger.warning("Redis 不可用，提醒调度降级（待发 %d 条）", len(payloads))
        return payloads
    try:
        for payload in payloads:
            await redis.xadd(
                REMINDER_STREAM_KEY, {"payload": json.dumps(payload, ensure_ascii=False)}
            )
    except Exception as exc:  # noqa: BLE001 - Redis 异常一律降级
        logger.warning("提醒入队失败，降级", extra={"reason": str(exc)})
    return payloads
