"""食物搜索测试（BE3）：中文词元命中、别名命中、status 过滤、未登录 1001。"""

from app.models import Food, FoodAlias


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
