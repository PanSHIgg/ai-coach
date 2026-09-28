"""饮食记录测试（BE3）：写后重算与 account 一致、PUT/DELETE 生效、行级隔离、列表筛选。"""

from datetime import datetime, timedelta, timezone

from app.core.security import create_access_token
from app.models import BodyProfile, Food, User
from app.services import account

TZ = timezone(timedelta(hours=8))


def _today() -> str:
    return datetime.now(TZ).date().isoformat()


async def _seed_food(
    db_session, *, name="清蒸鱼", kcal=120.0, protein=18.2, fat=4.5, carb=1.2
) -> Food:
    food = Food(
        name=name, calories_100g=kcal, protein_100g=protein, fat_100g=fat, carb_100g=carb, status=1
    )
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


async def _other_headers(db_session, openid: str = "other-openid") -> dict:
    user = User(openid=openid, gender=1)
    db_session.add(user)
    await db_session.flush()
    token = create_access_token(str(user.id), openid=user.openid)
    await db_session.commit()
    return {"Authorization": f"Bearer {token}"}


async def test_create_meal_recomputes_account(db_client, db_session, authed):
    food = await _seed_food(db_session)
    await _seed_profile(db_session, authed["user_id"])
    resp = await db_client.post(
        "/api/meal",
        headers=authed["headers"],
        json={"meal_type": 2, "food_id": food.id, "amount_g": 150, "source": 1},
    )
    body = resp.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["calories"] == round(120.0 * 150 / 100, 1)  # 180.0

    # 与 account 重算结果一致
    acct = await account.get_today(db_session, authed["user_id"])
    assert data["today_intake"] == acct.intake == 180.0
    assert data["today_left"] == acct.today_left

    # 列表落库可见，含食物名快照
    lst = (await db_client.get("/api/meal/list", headers=authed["headers"])).json()["data"]
    assert lst["page"]["total"] == 1
    assert lst["items"][0]["food_name"] == "清蒸鱼"
    assert lst["items"][0]["protein"] == round(18.2 * 1.5, 2)


async def test_update_meal_partial(db_client, db_session, authed):
    food = await _seed_food(db_session)
    await _seed_profile(db_session, authed["user_id"])
    created = (
        await db_client.post(
            "/api/meal",
            headers=authed["headers"],
            json={"meal_type": 2, "food_id": food.id, "amount_g": 100, "source": 3},
        )
    ).json()["data"]

    upd = await db_client.put(
        f"/api/meal/{created['id']}", headers=authed["headers"], json={"amount_g": 200}
    )
    body = upd.json()
    assert body["code"] == 0
    assert body["data"]["calories"] == round(120.0 * 2.0, 1)  # 240.0
    acct = await account.get_today(db_session, authed["user_id"])
    assert body["data"]["today_intake"] == acct.intake == 240.0
    assert body["data"]["today_left"] == acct.today_left


async def test_update_meal_requires_field_2001(db_client, db_session, authed):
    food = await _seed_food(db_session)
    await _seed_profile(db_session, authed["user_id"])
    created = (
        await db_client.post(
            "/api/meal",
            headers=authed["headers"],
            json={"meal_type": 2, "food_id": food.id, "amount_g": 100, "source": 3},
        )
    ).json()["data"]
    resp = await db_client.put(f"/api/meal/{created['id']}", headers=authed["headers"], json={})
    assert resp.status_code == 422
    assert resp.json()["code"] == 2001


async def test_delete_meal_recomputes(db_client, db_session, authed):
    food = await _seed_food(db_session)
    await _seed_profile(db_session, authed["user_id"])
    created = (
        await db_client.post(
            "/api/meal",
            headers=authed["headers"],
            json={"meal_type": 2, "food_id": food.id, "amount_g": 150, "source": 1},
        )
    ).json()["data"]
    resp = await db_client.delete(f"/api/meal/{created['id']}", headers=authed["headers"])
    assert resp.json()["data"]["deleted"] is True
    acct = await account.get_today(db_session, authed["user_id"])
    assert acct.intake == 0.0


async def test_meal_row_isolation(db_client, db_session, authed):
    food = await _seed_food(db_session)
    await _seed_profile(db_session, authed["user_id"])
    created = (
        await db_client.post(
            "/api/meal",
            headers=authed["headers"],
            json={"meal_type": 2, "food_id": food.id, "amount_g": 150, "source": 1},
        )
    ).json()["data"]
    other = await _other_headers(db_session)

    upd = await db_client.put(f"/api/meal/{created['id']}", headers=other, json={"amount_g": 100})
    assert upd.status_code == 404
    assert upd.json()["code"] == 3001
    dele = await db_client.delete(f"/api/meal/{created['id']}", headers=other)
    assert dele.status_code == 404
    assert dele.json()["code"] == 3001
    # 另一用户列表看不到该记录
    lst = (await db_client.get("/api/meal/list", headers=other)).json()["data"]
    assert lst["page"]["total"] == 0


async def test_create_meal_food_not_found_3001(db_client, db_session, authed):
    await _seed_profile(db_session, authed["user_id"])
    resp = await db_client.post(
        "/api/meal",
        headers=authed["headers"],
        json={"meal_type": 2, "food_id": 9999999, "amount_g": 100, "source": 1},
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == 3001


async def test_list_meal_filters(db_client, db_session, authed):
    food = await _seed_food(db_session)
    await _seed_profile(db_session, authed["user_id"])
    await db_client.post(
        "/api/meal",
        headers=authed["headers"],
        json={"meal_type": 1, "food_id": food.id, "amount_g": 100, "source": 3},
    )
    await db_client.post(
        "/api/meal",
        headers=authed["headers"],
        json={"meal_type": 2, "food_id": food.id, "amount_g": 100, "source": 3},
    )
    today = (
        await db_client.get(
            f"/api/meal/list?date={_today()}&meal_type=2", headers=authed["headers"]
        )
    ).json()["data"]
    assert today["page"]["total"] == 1
    assert today["items"][0]["meal_type"] == 2

    other_date = (
        await db_client.get("/api/meal/list?date=2000-01-01", headers=authed["headers"])
    ).json()["data"]
    assert other_date["page"]["total"] == 0
