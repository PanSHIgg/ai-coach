"""提醒订阅消费者（F-06 AI 主动介入推送）。

从 `notification_service.enqueue_due_reminders` 写入的 Redis Stream（`notification:reminders`）
读取提醒任务并处理：校验订阅仍有效 → 解析用户 openid → 调用
`notification_service.send_subscribe_message` 发送微信订阅消息。

设计（对齐 `app/tasks/snapshot.py` 的 enqueue/直调风格）：
- 消费组 `notification-reminders` + XACK，保证「至少一次」语义；
- 单条处理失败只记日志并 ACK，不阻断其余条目；
- Redis 不可用时优雅降级返回空列表（不抛异常）；`run_once` 在无 Redis 时把待发任务
  **转进程内直接处理**，保证离线可验证。

CLI（便于验证/补跑）：
    python -m app.tasks.reminder_consumer --once            # 调度到点提醒并消费（端到端）
    python -m app.tasks.reminder_consumer --once --at 11:00 # 指定调度时刻（验证用）
    python -m app.tasks.reminder_consumer --consume         # 仅消费既有 Stream
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.redis import get_redis
from app.db.session import get_sessionmaker
from app.models import Subscription, User
from app.services import notification_service
from app.services.notification_service import (
    REMINDER_STREAM_KEY,
    TZ,
    SendResult,
)

logger = get_logger(__name__)

GROUP_NAME = "notification-reminders"
CONSUMER_NAME = "reminder-worker-1"


async def _lookup_openid(session: AsyncSession, user_id: int) -> str | None:
    """按 user_id 取 openid（订阅消息 touser 所需）。"""
    return await session.scalar(select(User.openid).where(User.id == user_id))


async def process_reminder(session: AsyncSession, payload: dict) -> SendResult:
    """处理单条提醒任务：校验订阅有效 → 发送（无凭证时由 send 层降级）。"""
    user_id = int(payload["user_id"])
    template_type = int(payload["template_type"])

    active = await session.scalar(
        select(Subscription.id).where(
            Subscription.user_id == user_id,
            Subscription.template_type == template_type,
            Subscription.status == 1,
        )
    )
    if active is None:
        logger.info(
            "提醒已退订，跳过发送",
            extra={"user_id": user_id, "template_type": template_type},
        )
        return SendResult(
            user_id, template_type, sent=False, degraded=False, reason="unsubscribed"
        )

    openid = await _lookup_openid(session, user_id)
    return await notification_service.send_subscribe_message(
        user_id, template_type, openid=openid
    )


async def _ensure_group(redis) -> None:
    """幂等创建消费组（已存在时忽略 BUSYGROUP）。"""
    try:
        await redis.xgroup_create(REMINDER_STREAM_KEY, GROUP_NAME, id="0", mkstream=True)
    except Exception as exc:  # noqa: BLE001 - 已存在视为正常
        if "BUSYGROUP" not in str(exc):
            raise


async def consume_once(
    session: AsyncSession | None = None,
    *,
    count: int = 100,
    block_ms: int = 0,
    redis=None,
) -> list[SendResult]:
    """消费一轮：读取新消息 → 处理 → XACK。Redis 不可用返回 []（不抛）。"""
    client = redis or await get_redis()
    if client is None:
        logger.warning("Redis 不可用，提醒消费者降级（本轮跳过）")
        return []

    own_session = session is None
    if own_session:
        session = get_sessionmaker()()

    results: list[SendResult] = []
    try:
        await _ensure_group(client)
        entries = await client.xreadgroup(
            GROUP_NAME,
            CONSUMER_NAME,
            {REMINDER_STREAM_KEY: ">"},
            count=count,
            block=block_ms if block_ms > 0 else None,
        )
        for _stream, messages in entries or []:
            for msg_id, fields in messages:
                try:
                    payload = json.loads((fields or {}).get("payload") or "{}")
                    results.append(await process_reminder(session, payload))
                except Exception as exc:  # noqa: BLE001 - 单条失败不影响其余
                    logger.warning(
                        "提醒任务处理失败，跳过该条",
                        extra={"msg_id": msg_id, "reason": str(exc)},
                    )
                finally:
                    await client.xack(REMINDER_STREAM_KEY, GROUP_NAME, msg_id)
    except Exception as exc:  # noqa: BLE001 - 消费整体失败一律降级
        logger.warning("提醒消费失败，已降级", extra={"reason": str(exc)})
    finally:
        if own_session:
            await session.close()
    return results


async def run_once(
    session: AsyncSession | None = None, *, at: datetime | None = None
) -> list[SendResult]:
    """端到端一次：调度到点提醒 → 消费发送。

    - Redis 可用：入队到 Stream 后由 `consume_once` 消费；
    - Redis 不可用：`enqueue_due_reminders` 返回待发列表，转**进程内直接处理**（降级可验证）。
    """
    own_session = session is None
    if own_session:
        session = get_sessionmaker()()

    try:
        pending = await notification_service.enqueue_due_reminders(session, at=at)
        client = await get_redis()
        if client is None:
            logger.warning("Redis 不可用，提醒任务转进程内直接处理（降级）")
            return [await process_reminder(session, p) for p in pending]
        return await consume_once(session, redis=client)
    finally:
        if own_session:
            await session.close()


def _parse_hhmm(value: str) -> time:
    try:
        hh, mm = value.split(":")
        return time(int(hh), int(mm))
    except Exception as exc:  # noqa: BLE001 - 参数解析统一转为 argparse 错误
        raise argparse.ArgumentTypeError("时刻格式应为 HH:MM") from exc


def main(argv: list[str] | None = None) -> int:
    """CLI 入口：--once 端到端；--consume 仅消费；--at 指定调度时刻。"""
    parser = argparse.ArgumentParser(description="提醒订阅消费者（F-06 主动介入推送）")
    parser.add_argument("--once", action="store_true", help="调度到点提醒并消费（端到端）")
    parser.add_argument("--consume", action="store_true", help="仅消费既有 Stream（不重新调度）")
    parser.add_argument("--at", type=_parse_hhmm, default=None, help="调度时刻 HH:MM（验证用）")
    args = parser.parse_args(argv)

    at_dt = None
    if args.at is not None:
        at_dt = datetime.now(TZ).replace(
            hour=args.at.hour, minute=args.at.minute, second=0, microsecond=0
        )

    if args.consume and not args.once:
        results = asyncio.run(consume_once())
    else:
        results = asyncio.run(run_once(at=at_dt))

    sent = sum(1 for r in results if r.sent)
    degraded = sum(1 for r in results if r.degraded)
    print(f"处理 {len(results)} 条：已发送 {sent}，降级 {degraded}")
    for r in results:
        print(
            f"  user={r.user_id} type={r.template_type} "
            f"sent={r.sent} degraded={r.degraded} reason={r.reason}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
