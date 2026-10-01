"""提醒订阅测试（BE-n + F-06）：幂等 upsert、取消保留累计、行级隔离、调度降级、
场景模板覆盖、订阅消息无凭证降级、消费者处理入队任务。"""

from datetime import datetime, time, timedelta, timezone

from sqlalchemy import func, select

from app.core.security import create_access_token
from app.models import Subscription, User
from app.services import notification_service
from app.tasks import reminder_consumer

TZ = timezone(timedelta(hours=8))


async def _other_headers(db_session, openid: str = "sub-other") -> dict:
    user = User(openid=openid, gender=1)
    db_session.add(user)
    await db_session.flush()
    token = create_access_token(str(user.id), openid=user.openid)
    await db_session.commit()
    return {"Authorization": f"Bearer {token}"}


async def test_subscribe_idempotent(db_client, db_session, authed):
    first = (
        await db_client.post(
            "/api/subscription", headers=authed["headers"], json={"template_type": 1}
        )
    ).json()["data"]
    assert first["status"] == 1
    assert first["subscribe_count"] == 1
    assert first["last_subscribe_at"] is not None

    second = (
        await db_client.post(
            "/api/subscription", headers=authed["headers"], json={"template_type": 1}
        )
    ).json()["data"]
    assert second["status"] == 1
    assert second["subscribe_count"] == 2

    # 唯一约束：(user_id, template_type) 仅一行
    cnt = await db_session.scalar(
        select(func.count())
        .select_from(Subscription)
        .where(Subscription.user_id == authed["user_id"])
    )
    assert cnt == 1

    data = (await db_client.get("/api/subscription", headers=authed["headers"])).json()["data"]
    assert len(data["items"]) == 1
    assert data["items"][0]["template_type"] == 1
    assert data["items"][0]["subscribe_count"] == 2


async def test_cancel_keeps_count(db_client, db_session, authed):
    await db_client.post("/api/subscription", headers=authed["headers"], json={"template_type": 2})
    await db_client.post("/api/subscription", headers=authed["headers"], json={"template_type": 2})
    cancel = (
        await db_client.post(
            "/api/subscription/cancel", headers=authed["headers"], json={"template_type": 2}
        )
    ).json()["data"]
    assert cancel["status"] == 0
    assert cancel["subscribe_count"] == 2  # 保留累计

    # 再订阅 → status 恢复 1 且继续累加
    again = (
        await db_client.post(
            "/api/subscription", headers=authed["headers"], json={"template_type": 2}
        )
    ).json()["data"]
    assert again["status"] == 1
    assert again["subscribe_count"] == 3


async def test_cancel_without_record(db_client, db_session, authed):
    cancel = (
        await db_client.post(
            "/api/subscription/cancel", headers=authed["headers"], json={"template_type": 3}
        )
    ).json()["data"]
    assert cancel["status"] == 0
    assert cancel["subscribe_count"] == 0
    assert (await db_client.get("/api/subscription", headers=authed["headers"])).json()["data"][
        "items"
    ][0]["status"] == 0


async def test_subscription_isolation(db_client, db_session, authed):
    await db_client.post("/api/subscription", headers=authed["headers"], json={"template_type": 1})
    other = await _other_headers(db_session)
    assert (await db_client.get("/api/subscription", headers=other)).json()["data"]["items"] == []


async def test_enqueue_due_reminders_degrades_without_redis(db_session, authed):
    # 订阅午餐提醒（11:00）
    db_session.add(
        Subscription(
            user_id=authed["user_id"],
            template_type=1,
            status=1,
            subscribe_count=1,
            last_subscribe_at=datetime.now(TZ),
        )
    )
    await db_session.commit()
    at = datetime.now(TZ).replace(hour=11, minute=0, second=0, microsecond=0)
    # conftest 将 Redis 指向不可达端口 → 优雅降级，返回待发列表而非抛错
    pending = await notification_service.enqueue_due_reminders(db_session, at=at)
    assert any(p["user_id"] == authed["user_id"] and p["template_type"] == 1 for p in pending)

    # 非提醒窗口 → 空
    off = at.replace(hour=3, minute=0)
    assert await notification_service.enqueue_due_reminders(db_session, at=off) == []


def test_scene_templates_cover_documented_scenes():
    """F-06：场景模板覆盖文档所述 12+ 触发场景，模板 ID 为占位（不可当真实模板用）。"""
    scenes = notification_service.SCENE_TEMPLATES
    assert len(scenes) >= 12
    codes = {s.code for s in scenes.values()}
    # 文档明示场景：餐前、下午茶防诱惑、深夜防崩塌、超标后运动建议
    for expected in (
        "lunch_pre",
        "dinner_pre",
        "afternoon_tea_guard",
        "late_night_guard",
        "over_intake_sport",
    ):
        assert expected in codes
    # 占位模板 ID → 发送层判定为未配置
    for scene in scenes.values():
        assert scene.template_id.endswith(notification_service.PLACEHOLDER_SUFFIX)
    # 既有 4 类 template_type 定时语义不变
    assert notification_service.REMINDER_SCHEDULE[1] == time(11, 0)
    assert notification_service.REMINDER_SCHEDULE[2] == time(17, 0)
    assert notification_service.REMINDER_SCHEDULE[3] == time(22, 30)
    assert notification_service.REMINDER_SCHEDULE[4] == time(8, 0)


async def test_send_subscribe_message_degrades_without_credentials():
    """无凭证 → 明确降级为日志记录，sent=False 且 degraded=True，不伪造成功。"""
    result = await notification_service.send_subscribe_message(1, 1, openid="openid-x")
    assert result.sent is False
    assert result.degraded is True
    assert result.reason == "no_credentials"
    # 未启用时即使给了模板 ID 覆盖也不发送
    assert notification_service.subscribe_message_ready() is False


async def test_process_reminder_enqueued_task(db_session, authed):
    """消费者处理入队任务：订阅有效 → 走发送抽象（无凭证则降级）。"""
    db_session.add(
        Subscription(
            user_id=authed["user_id"],
            template_type=1,
            status=1,
            subscribe_count=1,
            last_subscribe_at=datetime.now(TZ),
        )
    )
    await db_session.commit()
    payload = {
        "user_id": authed["user_id"],
        "template_type": 1,
        "at": datetime.now(TZ).isoformat(),
    }
    result = await reminder_consumer.process_reminder(db_session, payload)
    assert result.user_id == authed["user_id"]
    assert result.template_type == 1
    assert result.sent is False
    assert result.degraded is True


async def test_process_reminder_skips_unsubscribed(db_session, authed):
    """未订阅（或已退订）的任务 → 不发送，且不算降级。"""
    payload = {"user_id": authed["user_id"], "template_type": 2, "at": datetime.now(TZ).isoformat()}
    result = await reminder_consumer.process_reminder(db_session, payload)
    assert result.sent is False
    assert result.degraded is False
    assert result.reason == "unsubscribed"


async def test_consume_once_degrades_without_redis(db_session):
    """Redis 不可达（conftest 钉死不可达端口）→ 消费降级返回空列表，不抛异常。"""
    assert await reminder_consumer.consume_once(db_session) == []


async def test_run_once_offline_processes_pending(db_session, authed):
    """无 Redis 时 run_once 端到端降级：入队待发 → 进程内直接处理。"""
    db_session.add(
        Subscription(
            user_id=authed["user_id"],
            template_type=1,
            status=1,
            subscribe_count=1,
            last_subscribe_at=datetime.now(TZ),
        )
    )
    await db_session.commit()
    at = datetime.now(TZ).replace(hour=11, minute=0, second=0, microsecond=0)
    results = await reminder_consumer.run_once(db_session, at=at)
    assert any(
        r.user_id == authed["user_id"] and r.template_type == 1 and r.degraded for r in results
    )
