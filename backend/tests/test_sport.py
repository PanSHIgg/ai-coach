"""运动记录测试（BE3）：MET 映射/入参、消耗公式、默认体重、列表与行级隔离。"""

from datetime import datetime, timedelta, timezone

from app.core.security import create_access_token
from app.models import BodyProfile, User
from app.services.record_service import compute_sport_calories, resolve_met

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


async def _other_headers(db_session, openid: str = "sport-other") -> dict:
    user = User(openid=openid, gender=1)
    db_session.add(user)
    await db_session.flush()
    token = create_access_token(str(user.id), openid=user.openid)
    await db_session.commit()
    return {"Authorization": f"Bearer {token}"}


def test_compute_sport_calories_and_met_resolution():
    # 【假设】calories = MET × 体重 × 时长(h)
    assert compute_sport_calories(met=8.0, weight_kg=70.0, duration_min=30) == round(
        8.0 * 70 * 0.5, 1
    )
    # 名字映射标准表
    assert resolve_met("慢跑", None) == 8.0
    assert resolve_met("快走", None) == 4.3
    assert resolve_met("跳绳", None) == 10.0
    # 入参 met 优先
    assert resolve_met("慢跑", 5.0) == 5.0
    # 未知名字走默认
    assert resolve_met("未知运动", None) == 6.0
    # 【假设】缺失体重默认 60kg
    assert compute_sport_calories(met=4.3, weight_kg=60.0, duration_min=30) == round(
        4.3 * 60 * 0.5, 1
    )


async def test_create_sport_met_from_name(db_client, db_session, authed):
    await _seed_profile(db_session, authed["user_id"], weight=70.0)
    resp = await db_client.post(
        "/api/sport", headers=authed["headers"], json={"sport_name": "慢跑", "duration_min": 30}
    )
    body = resp.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["calories"] == round(8.0 * 70 * 0.5, 1)  # 280.0
    assert data["today_burnt"] == 280.0


async def test_create_sport_explicit_met(db_client, db_session, authed):
    await _seed_profile(db_session, authed["user_id"], weight=70.0)
    resp = await db_client.post(
        "/api/sport", headers=authed["headers"], json={"met": 5.0, "duration_min": 60}
    )
    data = resp.json()["data"]
    assert data["calories"] == round(5.0 * 70 * 1.0, 1)  # 350.0
    assert data["today_burnt"] == 350.0


async def test_create_sport_accumulates_today_burnt(db_client, db_session, authed):
    await _seed_profile(db_session, authed["user_id"], weight=70.0)
    await db_client.post(
        "/api/sport", headers=authed["headers"], json={"sport_name": "慢跑", "duration_min": 30}
    )
    resp = await db_client.post(
        "/api/sport", headers=authed["headers"], json={"sport_name": "快走", "duration_min": 60}
    )
    data = resp.json()["data"]
    assert data["today_burnt"] == round(280.0 + 4.3 * 70 * 1.0, 1)


async def test_sport_without_profile_3001(db_client, authed):
    # 无档案 → 写后重算失败（未建档 3001），记录不落库
    resp = await db_client.post(
        "/api/sport", headers=authed["headers"], json={"sport_name": "慢跑", "duration_min": 30}
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == 3001


async def test_sport_list_and_isolation(db_client, db_session, authed):
    await _seed_profile(db_session, authed["user_id"], weight=70.0)
    from app.models import SportRecord

    db_session.add(
        SportRecord(
            user_id=authed["user_id"],
            sport_name="慢跑",
            met=8.0,
            duration_min=30,
            calories=280.0,
            record_at=datetime.now(TZ),
        )
    )
    await db_session.commit()

    lst = (
        await db_client.get(f"/api/sport/list?date={_today()}", headers=authed["headers"])
    ).json()["data"]
    assert lst["page"]["total"] == 1
    assert lst["items"][0]["sport_name"] == "慢跑"
    assert lst["items"][0]["calories"] == 280.0

    other = await _other_headers(db_session)
    other_lst = (await db_client.get("/api/sport/list", headers=other)).json()["data"]
    assert other_lst["page"]["total"] == 0
