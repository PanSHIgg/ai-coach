"""体重记录测试（BE-w）：CRUD、档案体重同步、行级隔离、趋势口径。"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.security import create_access_token
from app.models import BodyProfile, User, WeightRecord

TZ = timezone(timedelta(hours=8))


def _today() -> str:
    return datetime.now(TZ).date().isoformat()


async def _seed_profile(db_session, user_id: int, weight: float = 70.0) -> None:
    db_session.add(
        BodyProfile(
            user_id=user_id,
            gender=1,
            height_cm=175,
            age=30,
            current_weight=weight,
            target_type=1,
            activity_level=2,
            goal_pace=1,
        )
    )
    await db_session.commit()


async def _current_weight(db_session, user_id: int) -> float | None:
    profile = (
        await db_session.execute(select(BodyProfile).where(BodyProfile.user_id == user_id))
    ).scalar_one_or_none()
    return float(profile.current_weight) if profile and profile.current_weight is not None else None


async def _other_headers(db_session, openid: str = "weight-other") -> dict:
    user = User(openid=openid, gender=1)
    db_session.add(user)
    await db_session.flush()
    token = create_access_token(str(user.id), openid=user.openid)
    await db_session.commit()
    return {"Authorization": f"Bearer {token}"}


async def test_create_weight_syncs_profile(db_client, db_session, authed):
    await _seed_profile(db_session, authed["user_id"], weight=70.0)
    resp = await db_client.post("/api/weight", headers=authed["headers"], json={"weight": 68.5})
    body = resp.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["weight"] == 68.5
    assert data["record_at"] == _today()
    assert data["source"] == 1
    # 【假设】最新日期记录同步档案当前体重
    assert await _current_weight(db_session, authed["user_id"]) == 68.5


async def test_older_record_does_not_downgrade_profile(db_client, db_session, authed):
    await _seed_profile(db_session, authed["user_id"], weight=70.0)
    await db_client.post("/api/weight", headers=authed["headers"], json={"weight": 68.5})
    yesterday = (datetime.now(TZ).date() - timedelta(days=1)).isoformat()
    await db_client.post(
        "/api/weight", headers=authed["headers"], json={"weight": 60.0, "record_at": yesterday}
    )
    # 补录历史不应把当前体重改旧
    assert await _current_weight(db_session, authed["user_id"]) == 68.5


async def test_delete_weight_recomputes_profile(db_client, db_session, authed):
    """删除记录后按剩余最新一条体重记录重算档案当前体重（无记录则保持现值）。"""
    await _seed_profile(db_session, authed["user_id"], weight=70.0)
    today_id = (
        await db_client.post("/api/weight", headers=authed["headers"], json={"weight": 68.5})
    ).json()["data"]["id"]
    yesterday = (datetime.now(TZ).date() - timedelta(days=1)).isoformat()
    older_id = (
        await db_client.post(
            "/api/weight",
            headers=authed["headers"],
            json={"weight": 66.0, "record_at": yesterday},
        )
    ).json()["data"]["id"]
    # 补录历史不降级
    assert await _current_weight(db_session, authed["user_id"]) == 68.5

    # 删除最新（今日 68.5）→ 回退到剩余最新（昨日 66.0）
    await db_client.delete(f"/api/weight/{today_id}", headers=authed["headers"])
    assert await _current_weight(db_session, authed["user_id"]) == 66.0

    # 删除最后一条 → 无记录，保持现档案值不变
    await db_client.delete(f"/api/weight/{older_id}", headers=authed["headers"])
    assert await _current_weight(db_session, authed["user_id"]) == 66.0


async def test_weight_list_order_and_pagination(db_client, db_session, authed):
    today = datetime.now(TZ).date()
    for i, w in enumerate([70.0, 69.0, 68.0]):
        db_session.add(
            WeightRecord(user_id=authed["user_id"], weight=w, record_at=today - timedelta(days=i))
        )
    await db_session.commit()
    data = (
        await db_client.get("/api/weight/list?page=1&page_size=2", headers=authed["headers"])
    ).json()["data"]
    assert data["page"]["total"] == 3
    assert len(data["items"]) == 2
    # record_at DESC
    assert data["items"][0]["record_at"] == today.isoformat()
    assert data["items"][1]["record_at"] == (today - timedelta(days=1)).isoformat()


async def test_delete_weight_and_isolation(db_client, db_session, authed):
    await _seed_profile(db_session, authed["user_id"], weight=70.0)
    wid = (
        await db_client.post("/api/weight", headers=authed["headers"], json={"weight": 68.5})
    ).json()["data"]["id"]

    other = await _other_headers(db_session)
    deny = await db_client.delete(f"/api/weight/{wid}", headers=other)
    assert deny.status_code == 404
    assert deny.json()["code"] == 3001
    missing = await db_client.delete("/api/weight/9999999", headers=authed["headers"])
    assert missing.status_code == 404
    assert missing.json()["code"] == 3001

    ok_resp = await db_client.delete(f"/api/weight/{wid}", headers=authed["headers"])
    assert ok_resp.json()["data"]["deleted"] is True
    assert (await db_client.get("/api/weight/list", headers=authed["headers"])).json()["data"][
        "page"
    ]["total"] == 0


async def test_weight_trend(db_client, db_session, authed):
    today = datetime.now(TZ).date()
    # day-2=70, day-1=69, today 两条（同日取最后一条=67）
    db_session.add_all(
        [
            WeightRecord(
                user_id=authed["user_id"], weight=70.0, record_at=today - timedelta(days=2)
            ),
            WeightRecord(
                user_id=authed["user_id"], weight=69.0, record_at=today - timedelta(days=1)
            ),
            WeightRecord(user_id=authed["user_id"], weight=68.0, record_at=today),
            WeightRecord(user_id=authed["user_id"], weight=67.0, record_at=today),
        ]
    )
    await db_session.commit()
    data = (await db_client.get("/api/weight/trend", headers=authed["headers"])).json()["data"]
    assert [it["date"] for it in data["items"]] == [
        (today - timedelta(days=2)).isoformat(),
        (today - timedelta(days=1)).isoformat(),
        today.isoformat(),
    ]
    assert data["items"][-1]["weight"] == 67.0  # 同日取最后一条
    assert data["start_weight"] == 70.0
    assert data["latest_weight"] == 67.0
    assert data["change"] == -3.0


async def test_weight_trend_range_and_empty(db_client, authed):
    empty = (await db_client.get("/api/weight/trend", headers=authed["headers"])).json()["data"]
    assert empty["items"] == []
    assert (
        empty["start_weight"] is None and empty["latest_weight"] is None and empty["change"] is None
    )
