"""提醒订阅测试（BE-n）：幂等 upsert、取消保留累计、行级隔离、调度降级。"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.core.security import create_access_token
from app.models import Subscription, User
from app.services import notification_service

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
