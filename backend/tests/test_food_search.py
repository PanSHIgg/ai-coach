"""食物搜索测试（BE3）：中文词元命中、别名命中、status 过滤、未登录 1001。

F-02 追加：用户自定义食物创建（/api/food/custom）、仅本人可见、列表不泄露他人。
"""

import pytest
from sqlalchemy import select

from app.core.security import create_access_token
from app.models import Food, FoodAlias, User, UserBenefit


async def _seed(db_session):
    fish = Food(
        name="清蒸鱼", calories_100g=120.0, protein_100g=18.2, fat_100g=4.5, carb_100g=1.2, status=1
    )
    breast = Food(
        name="鸡胸脯肉",
        calories_100g=133.0,
        protein_100g=24.6,
        fat_100g=3.0,
        carb_100g=0.6,
        status=1,
    )
    disabled = Food(name="停用食物", calories_100g=100.0, status=0)
    db_session.add_all([fish, breast, disabled])
    await db_session.flush()
    db_session.add(FoodAlias(food_id=fish.id, alias="蒸福鱼"))
    db_session.add(FoodAlias(food_id=breast.id, alias="鸡胸肉"))
    await db_session.commit()
    return fish.id, breast.id


async def test_search_exact_chinese_name(db_client, db_session, authed):
    fish_id, _ = await _seed(db_session)
    resp = await db_client.post(
        "/api/food/search", headers=authed["headers"], json={"keyword": "清蒸鱼", "limit": 20}
    )
    body = resp.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["total"] >= 1
    assert fish_id in [it["id"] for it in data["items"]]
    hit = next(it for it in data["items"] if it["id"] == fish_id)
    assert hit["calories_100g"] == 120.0


async def test_search_by_alias(db_client, db_session, authed):
    _, breast_id = await _seed(db_session)
    # "鸡胸肉" 不是 name 子串，只能命中别名
    resp = await db_client.post(
        "/api/food/search", headers=authed["headers"], json={"keyword": "鸡胸肉", "limit": 20}
    )
    data = resp.json()["data"]
    assert breast_id in [it["id"] for it in data["items"]]


async def test_search_substring_by_name(db_client, db_session, authed):
    fish_id, _ = await _seed(db_session)
    resp = await db_client.post(
        "/api/food/search", headers=authed["headers"], json={"keyword": "蒸鱼", "limit": 20}
    )
    data = resp.json()["data"]
    assert fish_id in [it["id"] for it in data["items"]]


async def test_search_excludes_disabled(db_client, db_session, authed):
    await _seed(db_session)
    resp = await db_client.post(
        "/api/food/search", headers=authed["headers"], json={"keyword": "停用食物", "limit": 20}
    )
    data = resp.json()["data"]
    assert data["total"] == 0
    assert data["items"] == []


async def test_search_requires_auth_1001(db_client):
    resp = await db_client.post("/api/food/search", json={"keyword": "清蒸鱼"})
    assert resp.status_code == 401
    assert resp.json()["code"] == 1001


# ---------------------------------------------------------------------------
# F-02：用户自定义食物
# ---------------------------------------------------------------------------


async def _other_user(db_session) -> dict:
    """再建一个用户（与 authed 不同），返回 (user_id, 认证头)——用于验证可见性隔离。"""
    user = User(openid=f"other-openid-{id(db_session)}", nickname="他人", gender=1)
    db_session.add(user)
    await db_session.flush()
    db_session.add(UserBenefit(user_id=user.id, tier=0, ai_times_left=10))
    await db_session.commit()
    token = create_access_token(str(user.id), openid=user.openid)
    return {"user_id": user.id, "headers": {"Authorization": f"Bearer {token}"}}


async def test_create_custom_food_success(db_client, db_session, authed):
    resp = await db_client.post(
        "/api/food/custom",
        headers=authed["headers"],
        json={"name": "自制牛油果沙拉", "calories_100g": 88.5},
    )
    body = resp.json()
    assert resp.status_code == 200 and body["code"] == 0
    data = body["data"]
    assert data["name"] == "自制牛油果沙拉"
    assert data["calories_100g"] == 88.5
    assert data["audit_status"] == 0  # 待审核
    row = (await db_session.execute(select(Food).where(Food.id == data["id"]))).scalar_one()
    assert row.owner_user_id == authed["user_id"]


async def test_custom_food_visible_to_owner(db_client, authed):
    created = (
        await db_client.post(
            "/api/food/custom",
            headers=authed["headers"],
            json={"name": "自家卤蛋", "calories_100g": 150.0},
        )
    ).json()["data"]
    data = (
        await db_client.post(
            "/api/food/search", headers=authed["headers"], json={"keyword": "自家卤蛋", "limit": 20}
        )
    ).json()["data"]
    assert created["id"] in [it["id"] for it in data["items"]]
    assert data["total"] >= 1


async def test_custom_food_not_visible_to_others(db_client, db_session, authed):
    created = (
        await db_client.post(
            "/api/food/custom",
            headers=authed["headers"],
            json={"name": "秘密减脂餐", "calories_100g": 300.0},
        )
    ).json()["data"]
    other = await _other_user(db_session)
    data = (
        await db_client.post(
            "/api/food/search",
            headers=other["headers"],
            json={"keyword": "秘密减脂餐", "limit": 20},
        )
    ).json()["data"]
    # 不得泄露他人自定义食物
    assert data["total"] == 0
    assert data["items"] == []
    assert created["id"] not in [it["id"] for it in data["items"]]


@pytest.mark.parametrize(
    "payload",
    [
        {"calories_100g": 100},  # 缺 name
        {"name": "   ", "calories_100g": 100},  # name 去空白后为空
        {"name": "白开水", "calories_100g": 0},  # 热量须 > 0
        {"name": "白开水", "calories_100g": 1001},  # 热量超上界
    ],
    ids=["no_name", "blank_name", "kcal_zero", "kcal_high"],
)
async def test_create_custom_food_validation(db_client, authed, payload):
    resp = await db_client.post("/api/food/custom", headers=authed["headers"], json=payload)
    assert resp.status_code == 422
    assert resp.json()["code"] == 2001


async def test_create_custom_food_requires_auth_1001(db_client):
    resp = await db_client.post("/api/food/custom", json={"name": "白开水", "calories_100g": 0})
    assert resp.status_code == 401
    assert resp.json()["code"] == 1001
