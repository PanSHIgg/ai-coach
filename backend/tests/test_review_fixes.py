"""审查修复回归测试：数值上界（P1-2）、热量上界（P1-3）、image_url 置空（P2-9）、
已删用户 token（P2-10）。均走真实 DB（db_client + authed）。
"""

from datetime import timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.security import create_access_token
from app.models import BodyProfile, Food, MealRecord, User

TZ = timezone(timedelta(hours=8))

_PROFILE_BASE = {
    "gender": 1,
    "height_cm": 175,
    "birth_year": 1995,
    "current_weight": 70,
    "target_weight": 65,
    "target_type": 1,
    "activity_level": 3,
}


async def _seed_food(db_session, *, name="高热量食物", kcal=99999.9) -> Food:
    food = Food(name=name, calories_100g=kcal, status=1)
    db_session.add(food)
    await db_session.commit()
    return food


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


# ---------------------------------------------------------------------------
# P1-2 数值上界：越界 → 422/2001（防 DB 溢出 → 500）
# ---------------------------------------------------------------------------


async def test_meal_create_amount_over_limit_422(db_client, authed):
    resp = await db_client.post(
        "/api/meal",
        headers=authed["headers"],
        json={"meal_type": 2, "food_id": 1, "amount_g": 1000000, "source": 1},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == 2001


async def test_meal_update_amount_over_limit_422(db_client, authed):
    resp = await db_client.put("/api/meal/1", headers=authed["headers"], json={"amount_g": 1000000})
    assert resp.status_code == 422
    assert resp.json()["code"] == 2001


async def test_sport_duration_bounds_422(db_client, authed):
    for duration in (0, 1441):
        resp = await db_client.post(
            "/api/sport",
            headers=authed["headers"],
            json={"sport_name": "慢跑", "duration_min": duration},
        )
        assert resp.status_code == 422
        assert resp.json()["code"] == 2001


async def test_sport_met_over_limit_422(db_client, authed):
    resp = await db_client.post(
        "/api/sport", headers=authed["headers"], json={"met": 26, "duration_min": 30}
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == 2001


async def test_steps_over_limit_422(db_client, authed):
    resp = await db_client.post(
        "/api/steps/sync",
        headers=authed["headers"],
        json={"date": "2026-09-28", "steps": 1000000000000},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == 2001


# ---------------------------------------------------------------------------
# P1-3 计算热量超 NUMERIC 上限 → 422/2001（而非写库 500）
# ---------------------------------------------------------------------------


async def test_create_meal_calories_over_max_2001(db_client, db_session, authed):
    # 99999.9 kcal/100g × 10000g/100 = 9999990 > 999999.9
    food = await _seed_food(db_session)
    resp = await db_client.post(
        "/api/meal",
        headers=authed["headers"],
        json={"meal_type": 2, "food_id": food.id, "amount_g": 10000, "source": 1},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == 2001
    assert resp.json()["message"] == "分量超出合理范围"


async def test_update_meal_calories_over_max_2001(db_client, db_session, authed):
    await _seed_profile(db_session, authed["user_id"])
    food = await _seed_food(db_session)
    created = (
        await db_client.post(
            "/api/meal",
            headers=authed["headers"],
            json={"meal_type": 2, "food_id": food.id, "amount_g": 1, "source": 1},
        )
    ).json()["data"]
    resp = await db_client.put(
        f"/api/meal/{created['id']}", headers=authed["headers"], json={"amount_g": 10000}
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == 2001


# ---------------------------------------------------------------------------
# P2-9 update_meal 支持 image_url 显式置空（null），未传则保持不变
# ---------------------------------------------------------------------------


async def test_update_meal_clear_image_url(db_client, db_session, authed):
    await _seed_profile(db_session, authed["user_id"])
    food = await _seed_food(db_session, name="普通食物", kcal=120.0)
    created = (
        await db_client.post(
            "/api/meal",
            headers=authed["headers"],
            json={
                "meal_type": 2,
                "food_id": food.id,
                "amount_g": 100,
                "source": 1,
                "image_url": "http://cdn.example/1.png",
            },
        )
    ).json()["data"]

    # 未传 image_url → 保持原值
    await db_client.put(
        f"/api/meal/{created['id']}", headers=authed["headers"], json={"amount_g": 100}
    )
    db_session.expire_all()
    rec = (
        await db_session.execute(select(MealRecord).where(MealRecord.id == created["id"]))
    ).scalar_one()
    assert rec.image_url == "http://cdn.example/1.png"

    # 显式传 null → 置空
    resp = await db_client.put(
        f"/api/meal/{created['id']}", headers=authed["headers"], json={"image_url": None}
    )
    assert resp.status_code == 200
    assert resp.json()["code"] == 0
    db_session.expire_all()
    rec2 = (
        await db_session.execute(select(MealRecord).where(MealRecord.id == created["id"]))
    ).scalar_one()
    assert rec2.image_url is None


# ---------------------------------------------------------------------------
# P2-10 已删用户的 token → 401/1001（而非写接口外键 IntegrityError → 500）
# ---------------------------------------------------------------------------


async def test_deleted_user_token_1001(db_client, db_session):
    user = User(openid="deleted-user-openid", gender=1)
    db_session.add(user)
    await db_session.flush()
    token = create_access_token(str(user.id), openid=user.openid)
    # 删除用户（伪造「token 指向已删用户」）
    await db_session.delete(user)
    await db_session.commit()

    headers = {"Authorization": f"Bearer {token}"}
    me = await db_client.get("/api/auth/me", headers=headers)
    assert me.status_code == 401
    assert me.json()["code"] == 1001

    # 写接口同样在认证阶段被拦截（不会走到外键写入）
    write = await db_client.post("/api/weight", headers=headers, json={"weight": 68.5})
    assert write.status_code == 401
    assert write.json()["code"] == 1001


# ---------------------------------------------------------------------------
# P1-A 聚合上界：多条餐累加超当日上限 → 422/2001（防 daily_snapshot 写溢出 500）
# ---------------------------------------------------------------------------


async def test_meal_daily_aggregate_over_limit_422(db_client, db_session, authed):
    # 每条 6000 kcal（60kcal/100g × 10000g）；第 4 条使当日合计 24000 > 20000 上限
    await _seed_profile(db_session, authed["user_id"])
    food = Food(name="中热食物", calories_100g=60.0, status=1)
    db_session.add(food)
    await db_session.commit()
    payload = {"meal_type": 2, "food_id": food.id, "amount_g": 10000, "source": 1}
    for _ in range(3):
        ok_resp = await db_client.post("/api/meal", headers=authed["headers"], json=payload)
        assert ok_resp.status_code == 200
        assert ok_resp.json()["code"] == 0
    over = await db_client.post("/api/meal", headers=authed["headers"], json=payload)
    assert over.status_code == 422
    assert over.json()["code"] == 2001


# ---------------------------------------------------------------------------
# P1-A 单餐宏量营养溢出 NUMERIC(7,2) → 422/2001（而非写库 500）
# ---------------------------------------------------------------------------


async def test_meal_macro_over_limit_422(db_client, db_session, authed):
    # protein_100g 上限 9999.99（Numeric(6,2)）× 2000g/100 = 199999.8 > 99999.99
    food = Food(name="高蛋白食物", calories_100g=1.0, protein_100g=9999.99, status=1)
    db_session.add(food)
    await db_session.commit()
    resp = await db_client.post(
        "/api/meal",
        headers=authed["headers"],
        json={"meal_type": 2, "food_id": food.id, "amount_g": 2000, "source": 1},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == 2001


# ---------------------------------------------------------------------------
# P1-B 档案字段上界：birth_year / goal_pace 超限 → 422/2001
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("override", [{"birth_year": 100000}, {"goal_pace": 100000}])
async def test_profile_field_over_limit_422(db_client, authed, override: dict):
    resp = await db_client.post(
        "/api/body-profile", headers=authed["headers"], json={**_PROFILE_BASE, **override}
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == 2001


# ---------------------------------------------------------------------------
# P1-C 体重 source 越界 → 422/2001
# ---------------------------------------------------------------------------


async def test_weight_source_over_limit_422(db_client, authed):
    resp = await db_client.post(
        "/api/weight", headers=authed["headers"], json={"weight": 68.5, "source": 70000}
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == 2001


# ---------------------------------------------------------------------------
# P2-B 步数 hourly 非法键（非 0-23）/ 负值 / 单时值超限 → 422/2001
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("hourly", [{"24": 100}, {"-1": 100}, {"9": -1}, {"9": 300000}])
async def test_steps_hourly_out_of_range_422(db_client, authed, hourly: dict):
    resp = await db_client.post(
        "/api/steps/sync",
        headers=authed["headers"],
        json={"date": "2026-09-28", "steps": 8000, "hourly": hourly},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == 2001
