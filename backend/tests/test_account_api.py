"""热量账户接口测试（BE2）：/api/account/today、/api/account/trend。

覆盖：未建档→3001；有档案+饮食→intake/明细正确；today_left 满足 M1 对拍公式
（BMR×PAL − 摄入 + 运动 − TEF，误差 0）；趋势返回快照序列。
"""

from datetime import date, datetime, timedelta, timezone

from app.models import BodyProfile, MealRecord
from app.services import account, calorie

TZ = timezone(timedelta(hours=8))


def _today_tz() -> date:
    """业务当日（UTC+8），与 account 服务的日界口径一致。"""
    return datetime.now(TZ).date()


BMI_GENDER = 1
BMI_HEIGHT = 175.0
BMI_AGE = 31
BMI_WEIGHT = 70.0
LEVEL = 2


async def _make_profile(session, user_id: int, **overrides) -> None:
    fields = dict(
        user_id=user_id,
        gender=BMI_GENDER,
        height_cm=BMI_HEIGHT,
        birth_year=1995,
        age=BMI_AGE,
        current_weight=BMI_WEIGHT,
        target_type=1,
        activity_level=LEVEL,
        goal_pace=1,
    )
    fields.update(overrides)
    session.add(BodyProfile(**fields))
    await session.commit()


def _expected_today_left(*, intake: float, eat: float) -> float:
    bmr = calorie.bmr_mifflin_st_jeor(
        gender=BMI_GENDER, weight_kg=BMI_WEIGHT, height_cm=BMI_HEIGHT, age=BMI_AGE
    )
    pal = calorie.pal_for_level(LEVEL)
    tef = round(intake * calorie.TEF_RATE, 1)
    return round(bmr * pal - intake + eat - tef, 1)


async def test_account_today_without_profile_3001(db_client, authed):
    resp = await db_client.get("/api/account/today", headers=authed["headers"])
    assert resp.status_code == 404
    assert resp.json()["code"] == 3001


async def test_account_today_with_profile_and_meals(db_client, db_session, authed):
    uid = authed["user_id"]
    await _make_profile(db_session, uid, age=BMI_AGE)
    db_session.add_all(
        [
            MealRecord(
                user_id=uid,
                record_date=_today_tz(),
                meal_type=1,
                food_name_snapshot="燕麦",
                amount_g=100,
                calories=380,
                source=3,
            ),
            MealRecord(
                user_id=uid,
                record_date=_today_tz(),
                meal_type=2,
                food_name_snapshot="清蒸鱼",
                amount_g=150,
                calories=620,
                source=1,
            ),
        ]
    )
    await db_session.commit()

    resp = await db_client.get("/api/account/today", headers=authed["headers"])
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    data = body["data"]

    assert data["intake"] == 1000.0
    assert {m["meal_type"] for m in data["meals"]} == {1, 2}
    by_type = {m["meal_type"]: m for m in data["meals"]}
    assert by_type[1]["name"] == "早餐" and by_type[1]["calories"] == 380.0
    assert by_type[2]["name"] == "午餐" and by_type[2]["calories"] == 620.0

    # M1 对拍：today_left = BMR×PAL − 摄入 + 运动 − TEF，误差 0
    assert data["today_left"] == _expected_today_left(intake=1000.0, eat=0.0)
    # 无步数记录 → 走 PAL 估算（未校准）
    assert data["calibration_used"] is False
    assert data["steps"] == 0
    assert data["neat"] == calorie.state_neat(weight_kg=BMI_WEIGHT, activity_level=LEVEL)


async def test_account_today_aggregate_over_limit_422(db_client, db_session, authed):
    """当日摄入合计超 daily_snapshot.intake 的 NUMERIC(7,1) 上限 → 422/2001（而非写库 500）。"""
    uid = authed["user_id"]
    await _make_profile(db_session, uid, age=BMI_AGE)
    db_session.add_all(
        [
            MealRecord(
                user_id=uid,
                record_date=_today_tz(),
                meal_type=1,
                food_name_snapshot="超高",
                amount_g=100,
                calories=600000,
                source=3,
            ),
            MealRecord(
                user_id=uid,
                record_date=_today_tz(),
                meal_type=2,
                food_name_snapshot="超高",
                amount_g=100,
                calories=600000,
                source=1,
            ),
        ]
    )
    await db_session.commit()

    resp = await db_client.get("/api/account/today", headers=authed["headers"])
    assert resp.status_code == 422
    assert resp.json()["code"] == 2001


async def test_today_status_persists_and_pal_follows(db_client, db_session, authed):
    """F-01：POST /api/account/today-status 写入当日状态 → 当日 PAL/NEAT 取该状态并落库回读。"""
    uid = authed["user_id"]
    await _make_profile(db_session, uid, age=BMI_AGE)

    resp = await db_client.post(
        "/api/account/today-status", json={"activity_level": 5}, headers=authed["headers"]
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["activity_level"] == 5
    assert data["pal"] == calorie.pal_for_level(5) == 2.0
    assert data["neat"] == calorie.state_neat(weight_kg=BMI_WEIGHT, activity_level=5)

    # GET today 回读：状态已落库，PAL 仍按当日状态（5），不受建档 activity_level=2 影响
    resp2 = await db_client.get("/api/account/today", headers=authed["headers"])
    data2 = resp2.json()["data"]
    assert data2["activity_level"] == 5
    assert data2["pal"] == 2.0
    assert data2["neat"] == calorie.state_neat(weight_kg=BMI_WEIGHT, activity_level=5)


async def test_today_status_unset_falls_back_to_profile(db_client, db_session, authed):
    """F-01：未选当日状态 → activity_level=null，PAL 回退建档 activity_level（不点用默认 PAL）。"""
    uid = authed["user_id"]
    await _make_profile(db_session, uid, age=BMI_AGE)

    resp = await db_client.get("/api/account/today", headers=authed["headers"])
    data = resp.json()["data"]
    assert data["activity_level"] is None
    assert data["pal"] == calorie.pal_for_level(LEVEL) == 1.4


async def test_account_trend_returns_snapshot_series(db_client, db_session, authed):
    uid = authed["user_id"]
    await _make_profile(db_session, uid, age=BMI_AGE)
    today = date.today()
    yesterday = today - timedelta(days=1)

    # 造两条快照：昨天 + 今天（account.upsert_snapshot 幂等）
    await account.upsert_snapshot(db_session, uid, yesterday)
    await account.upsert_snapshot(db_session, uid, today)

    resp = await db_client.get(
        f"/api/account/trend?start_date={yesterday.isoformat()}&end_date={today.isoformat()}",
        headers=authed["headers"],
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    items = body["data"]["items"]
    assert [it["date"] for it in items] == [yesterday.isoformat(), today.isoformat()]
    # 无摄入/运动 → 快照数值来自引擎
    assert all(it["steps"] == 0 for it in items)
    assert items[0]["tee"] == items[1]["tee"]


async def test_account_trend_default_last_7_days(db_client, db_session, authed):
    uid = authed["user_id"]
    await _make_profile(db_session, uid, age=BMI_AGE)
    today = date.today()
    await account.upsert_snapshot(db_session, uid, today)
    # 8 天前不在默认窗口内
    await account.upsert_snapshot(db_session, uid, today - timedelta(days=8))

    resp = await db_client.get("/api/account/trend", headers=authed["headers"])
    assert resp.status_code == 200
    dates = [it["date"] for it in resp.json()["data"]["items"]]
    assert today.isoformat() in dates
    assert (today - timedelta(days=8)).isoformat() not in dates
