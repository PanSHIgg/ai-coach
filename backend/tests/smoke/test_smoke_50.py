"""Phase 5 · F8 发布级端到端冒烟（50+ 条，跨模块串联「能跑通」）。

**为何单开文件（AGENTS §2.9「新增测试文件须说明不可被现有文件容纳的理由」）**：
本文件是**发布级端到端冒烟**，目标是验证「登录→建档→记餐→查账户→AI→商家→下单支付核销
→社区→内容审核→管理后台」等**跨模块串联链路可跑通**，而非模块内分支/边界的正确性
（后者已由 tests/test_*.py 各域单元/接口测试逐条覆盖）。因此本文件的断言刻意保持**粗粒度**
（envelope code==0 / 状态字段流转 / 资源可见性），**不复用**既有文件的细节断言，也不与之重复；
它填的是「现有测试文件都不做：把多个模块在一次请求序列里串起来」这一空白。

对齐真源：`docs/split/09-排期与验收交付.md` §11.3 里程碑验收（M1–M4）与 §12.1 功能验收项、
`docs/split/07-测试方案.md` §9.7 上线通过标准「冒烟用例 50 条全部通过」。

fixture 复用 conftest 既有 `db_client / db_session / authed / admin_authed`（未改 conftest）。
真实 DB；AI 无 Key 环境自动落 mock（`app/ai/factory.py`），无需联网。
"""

import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.security import create_access_token
from app.models import (
    Challenge,
    CommunityGroup,
    Coupon,
    DailySnapshot,
    Food,
    Merchant,
    MerchantSku,
    SkuCatalog,
    User,
)
from app.services.order_service import notify_sign

TZ = timezone(timedelta(hours=8))


# ---------------------------------------------------------------------------
# 造数 / 通用助手（不依赖各域测试文件；不 import 其它 test_*）
# ---------------------------------------------------------------------------


def _today() -> str:
    return datetime.now(TZ).date().isoformat()


def _future_iso(days: int = 2) -> str:
    return (datetime.now(TZ) + timedelta(days=days)).isoformat()


async def _login(db_client, code: str = "smoke") -> dict:
    """微信登录（mock code2session）→ 返回 {token, refresh_token, user_id, headers}。"""
    body = (await db_client.post("/api/auth/login", json={"code": code})).json()
    assert body["code"] == 0, body
    data = body["data"]
    return {
        "token": data["token"],
        "refresh_token": data["refresh_token"],
        "user_id": data["user"]["id"],
        "headers": {"Authorization": f"Bearer {data['token']}"},
    }


async def _build_profile(db_client, headers: dict) -> dict:
    body = (
        await db_client.post(
            "/api/body-profile",
            headers=headers,
            json={
                "gender": 1,
                "height_cm": 175.0,
                "birth_year": 1995,
                "current_weight": 70.0,
                "target_weight": 65.0,
                "target_type": 1,
                "activity_level": 3,
            },
        )
    ).json()
    assert body["code"] == 0, body
    return body["data"]


async def _seed_food(
    db_session, name: str = "清蒸鱼", kcal: float = 120.0, category: str | None = None
) -> Food:
    food = Food(
        name=name,
        calories_100g=kcal,
        protein_100g=18.2,
        fat_100g=4.5,
        carb_100g=1.2,
        status=1,
        category=category,
    )
    db_session.add(food)
    await db_session.commit()
    return food


async def _seed_merchant(
    db_session,
    name: str = "轻食一号店",
    *,
    category: str = "轻食",
    status: int = 1,
    audit_status: int = 1,
    lat: float | None = None,
    lng: float | None = None,
) -> Merchant:
    m = Merchant(
        name=name,
        category=category,
        address="XX路1号",
        status=status,
        audit_status=audit_status,
        lat=lat,
        lng=lng,
    )
    db_session.add(m)
    await db_session.commit()
    return m


async def _seed_sku(
    db_session,
    merchant_id: int,
    code: str = "FD-001",
    price: float = 25.0,
    stock: int = -1,
    status: int = 1,
) -> MerchantSku:
    catalog_id = (
        await db_session.execute(select(SkuCatalog.id).where(SkuCatalog.code == code))
    ).scalar_one()
    sku = MerchantSku(
        merchant_id=merchant_id, catalog_id=catalog_id, price=price, stock=stock, status=status
    )
    db_session.add(sku)
    await db_session.commit()
    return sku


async def _seed_coupon(db_session, user_id: int, **kw) -> Coupon:
    now = datetime.now(UTC)
    fields = dict(
        code=f"CP-{uuid.uuid4().hex[:16]}",
        type=1,
        scope=4,
        amount=5.0,
        discount_rate=None,
        min_spend=0.0,
        merchant_id=None,
        status=1,
        valid_from=now - timedelta(days=1),
        valid_to=now + timedelta(days=30),
        obtain_user_id=user_id,
    )
    fields.update(kw)
    coupon = Coupon(**fields)
    db_session.add(coupon)
    await db_session.commit()
    return coupon


async def _seed_group(db_session, name: str = "减脂餐交流社") -> CommunityGroup:
    group = CommunityGroup(name=name, category="减脂", member_count=0, city="上海")
    db_session.add(group)
    await db_session.commit()
    return group


async def _seed_challenge(db_session, title: str = "21天不饿肚子挑战赛") -> Challenge:
    challenge = Challenge(title=title, join_count=0, status=1)
    db_session.add(challenge)
    await db_session.commit()
    return challenge


async def _other_user(db_session, openid: str = "smoke-other") -> dict:
    user = User(openid=openid, gender=1)
    db_session.add(user)
    await db_session.flush()
    token = create_access_token(str(user.id), openid=user.openid)
    await db_session.commit()
    return {"user_id": user.id, "headers": {"Authorization": f"Bearer {token}"}}


async def _admin_headers(db_client, admin_authed: dict) -> dict:
    body = (await db_client.post("/api/admin/login", json=admin_authed)).json()
    assert body["code"] == 0, body
    return {"Authorization": f"Bearer {body['data']['token']}"}


async def _create_order(
    db_client, headers: dict, merchant_id: int, items: list, coupon_id=None
) -> dict:
    payload: dict = {"merchant_id": merchant_id, "items": items}
    if coupon_id is not None:
        payload["coupon_id"] = coupon_id
    body = (await db_client.post("/api/order", headers=headers, json=payload)).json()
    assert body["code"] == 0, body
    return body["data"]


async def _notify(db_client, order_no: str, amount: float):
    return await db_client.post(
        "/api/order/notify",
        json={"order_no": order_no, "amount": amount, "sign": notify_sign(order_no, amount)},
    )


async def _paid_order(
    db_client, db_session, headers: dict, merchant_id: int, code: str = "FD-001"
) -> dict:
    """下单 → 支付回调 → 返回已支付订单数据（status=2）。"""
    sku = await _seed_sku(db_session, merchant_id, code=code)
    data = await _create_order(db_client, headers, merchant_id, [{"sku_id": sku.id, "qty": 1}])
    resp = await _notify(db_client, data["order_no"], data["pay_amount"])
    assert resp.status_code == 200 and resp.json()["code"] == 0, resp.text
    return data


# ---------------------------------------------------------------------------
# M1：认证 / 建档 / 记录 / 热量账户 / 体重 / 订阅（SMK-01 ~ SMK-12）
# ---------------------------------------------------------------------------


async def test_smoke_01_login_profile_account_loop(db_client, db_session):
    """登录 → /auth/me → 建档 → 首页账户：新用户核心闭环。"""
    session = await _login(db_client, "smoke-01")
    me = (await db_client.get("/api/auth/me", headers=session["headers"])).json()
    assert me["code"] == 0 and me["data"]["id"] == session["user_id"]
    prof = await _build_profile(db_client, session["headers"])
    assert prof["bmr"] > 0 and prof["target_calories"] > 0
    today = (await db_client.get("/api/account/today", headers=session["headers"])).json()
    assert today["code"] == 0 and today["data"]["date"] == _today()


async def test_smoke_02_refresh_token_roundtrip(db_client, db_session):
    """登录 → refresh 换新 access → 新 token 可访问 /auth/me。"""
    session = await _login(db_client, "smoke-02")
    refreshed = (
        await db_client.post("/api/auth/refresh", json={"refresh_token": session["refresh_token"]})
    ).json()
    assert refreshed["code"] == 0
    new_headers = {"Authorization": f"Bearer {refreshed['data']['token']}"}
    me = (await db_client.get("/api/auth/me", headers=new_headers)).json()
    assert me["code"] == 0 and me["data"]["id"] == session["user_id"]


async def test_smoke_03_profile_get_null_before_create(db_client, db_session):
    """新登录用户查询身体档案：未建档返回 data=null（异常态-空）。"""
    session = await _login(db_client, "smoke-03")
    body = (await db_client.get("/api/body-profile", headers=session["headers"])).json()
    assert body["code"] == 0 and body["data"] is None


async def test_smoke_04_meal_write_account_list(db_client, db_session, authed):
    """建档 → 记餐 → 账户摄入增加 → 记录列表可见。"""
    await _build_profile(db_client, authed["headers"])
    food = await _seed_food(db_session)
    created = (
        await db_client.post(
            "/api/meal",
            headers=authed["headers"],
            json={"meal_type": 2, "food_id": food.id, "amount_g": 150, "source": 1},
        )
    ).json()
    assert created["code"] == 0
    today = (await db_client.get("/api/account/today", headers=authed["headers"])).json()["data"]
    assert today["intake"] == created["data"]["today_intake"] > 0
    meals = (await db_client.get("/api/meal/list", headers=authed["headers"])).json()["data"]
    assert meals["page"]["total"] == 1 and meals["items"][0]["food_name"] == "清蒸鱼"


async def test_smoke_05_meal_update_delete_loop(db_client, db_session, authed):
    """记餐 → 编辑 → 删除 → 列表回空（CRUD 全链路）。"""
    await _build_profile(db_client, authed["headers"])
    food = await _seed_food(db_session)
    meal = (
        await db_client.post(
            "/api/meal",
            headers=authed["headers"],
            json={"meal_type": 1, "food_id": food.id, "amount_g": 100, "source": 3},
        )
    ).json()["data"]
    updated = (
        await db_client.put(
            f"/api/meal/{meal['id']}", headers=authed["headers"], json={"amount_g": 200}
        )
    ).json()
    assert updated["code"] == 0 and updated["data"]["calories"] > meal["calories"]
    deleted = (await db_client.delete(f"/api/meal/{meal['id']}", headers=authed["headers"])).json()
    assert deleted["code"] == 0 and deleted["data"]["deleted"] is True
    meals = (await db_client.get("/api/meal/list", headers=authed["headers"])).json()["data"]
    assert meals["page"]["total"] == 0


async def test_smoke_06_food_search_to_meal(db_client, db_session, authed):
    """食物搜索 → 用命中 food_id 直接记餐（搜索↔记录串联）。"""
    await _build_profile(db_client, authed["headers"])
    food = await _seed_food(db_session, "燕麦", 380.0)
    search = (
        await db_client.post(
            "/api/food/search", headers=authed["headers"], json={"keyword": "燕麦"}
        )
    ).json()
    assert search["code"] == 0
    hit = next(item for item in search["data"]["items"] if item["id"] == food.id)
    created = (
        await db_client.post(
            "/api/meal",
            headers=authed["headers"],
            json={"meal_type": 1, "food_id": hit["id"], "amount_g": 100, "source": 1},
        )
    ).json()
    assert created["code"] == 0 and created["data"]["calories"] == 380.0


async def test_smoke_07_sport_write_account_list(db_client, db_session, authed):
    """新增运动 → 账户消耗增加 → 运动列表可见。"""
    await _build_profile(db_client, authed["headers"])
    created = (
        await db_client.post(
            "/api/sport", headers=authed["headers"], json={"sport_name": "慢跑", "duration_min": 30}
        )
    ).json()
    assert created["code"] == 0 and created["data"]["calories"] > 0
    today = (await db_client.get("/api/account/today", headers=authed["headers"])).json()["data"]
    assert today["calories_burnt"] == created["data"]["calories"]
    sports = (await db_client.get("/api/sport/list", headers=authed["headers"])).json()["data"]
    assert sports["page"]["total"] == 1


async def test_smoke_08_steps_sync_account(db_client, db_session, authed):
    """同步步数 → 账户步数与 NEAT 校准生效。"""
    await _build_profile(db_client, authed["headers"])
    synced = (
        await db_client.post(
            "/api/steps/sync", headers=authed["headers"], json={"date": _today(), "steps": 12000}
        )
    ).json()
    assert synced["code"] == 0 and synced["data"]["neat_calibrated"] > 0
    today = (await db_client.get("/api/account/today", headers=authed["headers"])).json()["data"]
    assert today["steps"] == 12000 and today["calibration_used"] is True


async def test_smoke_09_account_trend_after_records(db_client, db_session, authed):
    """记餐后查询账户趋势：按日返回 items。"""
    await _build_profile(db_client, authed["headers"])
    food = await _seed_food(db_session)
    await db_client.post(
        "/api/meal",
        headers=authed["headers"],
        json={"meal_type": 2, "food_id": food.id, "amount_g": 100, "source": 1},
    )
    trend = (await db_client.get("/api/account/trend", headers=authed["headers"])).json()
    assert (
        trend["code"] == 0 and isinstance(trend["data"]["items"], list) and trend["data"]["items"]
    )


async def test_smoke_10_weight_crud_trend(db_client, db_session, authed):
    """体重：新增 → 列表 → 趋势 → 删除 → 列表回空。"""
    created = (
        await db_client.post("/api/weight", headers=authed["headers"], json={"weight": 68.5})
    ).json()["data"]
    listed = (await db_client.get("/api/weight/list", headers=authed["headers"])).json()["data"]
    assert listed["page"]["total"] == 1
    trend = (await db_client.get("/api/weight/trend", headers=authed["headers"])).json()["data"]
    assert trend["latest_weight"] == 68.5
    await db_client.delete(f"/api/weight/{created['id']}", headers=authed["headers"])
    listed2 = (await db_client.get("/api/weight/list", headers=authed["headers"])).json()["data"]
    assert listed2["page"]["total"] == 0


async def test_smoke_11_subscription_subscribe_list_cancel(db_client, db_session, authed):
    """订阅提醒：订阅 → 列表可见 → 取消。"""
    sub = (
        await db_client.post(
            "/api/subscription", headers=authed["headers"], json={"template_type": 1}
        )
    ).json()["data"]
    assert sub["status"] == 1
    listed = (await db_client.get("/api/subscription", headers=authed["headers"])).json()["data"]
    assert [it["template_type"] for it in listed["items"]] == [1]
    cancel = (
        await db_client.post(
            "/api/subscription/cancel", headers=authed["headers"], json={"template_type": 1}
        )
    ).json()["data"]
    assert cancel["status"] == 0


async def test_smoke_12_recognize_to_meal(db_client, db_session, authed):
    """拍照识别（mock）→ 返回识别项 → 用识别分量记餐（AI↔记录串联）。"""
    await _build_profile(db_client, authed["headers"])
    food = await _seed_food(db_session, "清蒸鱼", 120.0)
    recognized = (
        await db_client.post(
            "/api/meal/recognize",
            headers=authed["headers"],
            files={"image": ("meal.jpg", b"\xff\xd8\xff-demo", "image/jpeg")},
        )
    ).json()
    assert recognized["code"] == 0 and recognized["data"]["items"]
    item = recognized["data"]["items"][0]
    created = (
        await db_client.post(
            "/api/meal",
            headers=authed["headers"],
            json={
                "meal_type": 2,
                "food_id": food.id,
                "amount_g": item.get("amount_g") or 100,
                "source": 1,
            },
        )
    ).json()
    assert created["code"] == 0


# ---------------------------------------------------------------------------
# M2：AI（SMK-13 ~ SMK-16）
# ---------------------------------------------------------------------------


async def test_smoke_13_ai_chat_then_times(db_client, db_session, authed):
    """AI 对话（无 Key 落 mock）→ 剩余次数扣减，/ai/times 一致。"""
    before = (await db_client.get("/api/ai/times", headers=authed["headers"])).json()["data"]
    chat = (
        await db_client.post(
            "/api/ai/chat",
            headers=authed["headers"],
            json={"session_id": str(uuid.uuid4()), "message": "下午饿了能吃什么"},
        )
    ).json()
    assert chat["code"] == 0 and chat["data"]["reply"]
    after = (await db_client.get("/api/ai/times", headers=authed["headers"])).json()["data"]
    assert after["times_left"] == before["times_left"] - 1


async def test_smoke_14_ai_recommend_options(db_client, db_session, authed):
    """饭点决策推荐 → 返回 options（含理由）。"""
    await _seed_food(db_session, "杂粮饭", 150.0, category="主食")
    body = (
        await db_client.post("/api/ai/recommend", headers=authed["headers"], json={"meal_type": 2})
    ).json()
    assert body["code"] == 0 and body["data"]["options"]


async def test_smoke_15_ai_weekly_comment(db_client, db_session, authed):
    """AI 周点评 → 返回免责声明与亮点（周报链路）。"""
    db_session.add(
        DailySnapshot(
            user_id=authed["user_id"],
            snapshot_date=datetime.now(TZ).date(),
            intake=1500,
            deficit=-400,
            steps=9000,
        )
    )
    await db_session.commit()
    body = (
        await db_client.post("/api/ai/weekly-comment", headers=authed["headers"], json={})
    ).json()
    assert body["code"] == 0 and body["data"]["content"] and body["data"]["highlights"]


async def test_smoke_16_ai_quota_exhausted_4001(db_client, db_session, authed):
    """AI 次数用尽 → 409/4001（异常态-无权益）。"""
    from app.models import UserBenefit

    benefit = await db_session.scalar(
        select(UserBenefit).where(UserBenefit.user_id == authed["user_id"])
    )
    benefit.ai_times_left = 0
    benefit.ai_times_reset_at = datetime.now(UTC)  # 非跨日：不触发重置
    await db_session.commit()
    resp = await db_client.post(
        "/api/ai/chat",
        headers=authed["headers"],
        json={"session_id": str(uuid.uuid4()), "message": "饿了"},
    )
    assert resp.status_code == 409 and resp.json()["code"] == 4001


# ---------------------------------------------------------------------------
# M3：商家 / 订单 / 支付 / 核销 / 券（SMK-17 ~ SMK-30）
# ---------------------------------------------------------------------------


async def test_smoke_17_merchant_browse_flow(db_client, db_session, authed):
    """商家列表（LBS）→ 商家详情（含 SKU）→ 标准目录。"""
    merchant = await _seed_merchant(db_session, "浏览店", lat=31.2304, lng=121.4737)
    await _seed_sku(db_session, merchant.id, "FD-001", price=28.0)
    listed = (
        await db_client.get(
            "/api/merchant/list", headers=authed["headers"], params={"lat": 31.223, "lng": 121.482}
        )
    ).json()
    assert listed["code"] == 0 and any(it["id"] == merchant.id for it in listed["data"]["items"])
    detail = (await db_client.get(f"/api/merchant/{merchant.id}", headers=authed["headers"])).json()
    assert detail["code"] == 0 and detail["data"]["skus"]
    catalog = (await db_client.get("/api/sku/catalog", headers=authed["headers"])).json()
    assert catalog["code"] == 0 and len(catalog["data"]["items"]) >= 5


async def test_smoke_18_order_create_visible_in_list(db_client, db_session, authed):
    """下单 → 订单列表可见（待支付 status=1）。"""
    merchant = await _seed_merchant(db_session)
    sku = await _seed_sku(db_session, merchant.id)
    data = await _create_order(
        db_client, authed["headers"], merchant.id, [{"sku_id": sku.id, "qty": 1}]
    )
    listed = (await db_client.get("/api/order/list", headers=authed["headers"])).json()["data"]
    row = next(it for it in listed["items"] if it["order_no"] == data["order_no"])
    assert row["status"] == 1


async def test_smoke_19_order_pay_notify_list(db_client, db_session, authed):
    """下单 → pay 预下单 → notify 回调 → 列表 status=2（已支付待核销）。"""
    merchant = await _seed_merchant(db_session)
    sku = await _seed_sku(db_session, merchant.id)
    data = await _create_order(
        db_client, authed["headers"], merchant.id, [{"sku_id": sku.id, "qty": 1}]
    )
    pay = (
        await db_client.post(f"/api/order/{data['order_id']}/pay", headers=authed["headers"])
    ).json()
    assert pay["code"] == 0
    assert (await _notify(db_client, data["order_no"], data["pay_amount"])).json()["code"] == 0
    listed = (await db_client.get("/api/order/list?status=2", headers=authed["headers"])).json()[
        "data"
    ]
    assert any(it["order_no"] == data["order_no"] for it in listed["items"])


async def test_smoke_20_order_full_loop_redeem(db_client, db_session, authed):
    """下单 → 支付回调 → 核销 → 列表 status=3（交易闭环一气呵成）。"""
    merchant = await _seed_merchant(db_session)
    data = await _paid_order(db_client, db_session, authed["headers"], merchant.id)
    listed = (await db_client.get("/api/order/list", headers=authed["headers"])).json()["data"]
    order = next(it for it in listed["items"] if it["order_no"] == data["order_no"])
    redeem_code = order["redeem_code"]
    assert redeem_code
    redeemed = (
        await db_client.post(
            f"/api/order/{data['order_id']}/redeem",
            headers=authed["headers"],
            json={"redeem_code": redeem_code, "merchant_id": merchant.id},
        )
    ).json()
    assert redeemed["code"] == 0 and redeemed["data"]["status"] == "redeemed"
    after = (await db_client.get("/api/order/list?status=3", headers=authed["headers"])).json()[
        "data"
    ]
    assert any(it["order_no"] == data["order_no"] for it in after["items"])


async def test_smoke_21_order_with_coupon_discount(db_client, db_session, authed):
    """带券下单 → 服务端重算抵扣 → 券列表状态变为已用/占用。"""
    merchant = await _seed_merchant(db_session)
    sku = await _seed_sku(db_session, merchant.id, price=30.0)
    coupon = await _seed_coupon(db_session, authed["user_id"], amount=5.0, min_spend=0.0)
    data = await _create_order(
        db_client,
        authed["headers"],
        merchant.id,
        [{"sku_id": sku.id, "qty": 1}],
        coupon_id=coupon.id,
    )
    assert data["discount_amount"] == 5.0 and data["pay_amount"] == 25.0
    coupons = (await db_client.get("/api/coupon/list", headers=authed["headers"])).json()["data"]
    assert next(it for it in coupons["items"] if it["id"] == coupon.id)["status"] == 2


async def test_smoke_22_order_expire_pay_5003(db_client, db_session, authed):
    """下单 → 过期 → pay → 409/5003（异常态-超时）。"""
    from app.models import Order

    merchant = await _seed_merchant(db_session)
    sku = await _seed_sku(db_session, merchant.id)
    data = await _create_order(
        db_client, authed["headers"], merchant.id, [{"sku_id": sku.id, "qty": 1}]
    )
    order = await db_session.get(Order, data["order_id"])
    order.expire_at = datetime.now(UTC) - timedelta(minutes=1)
    await db_session.commit()
    resp = await db_client.post(f"/api/order/{data['order_id']}/pay", headers=authed["headers"])
    assert resp.status_code == 409 and resp.json()["code"] == 5003


async def test_smoke_23_order_foreign_user_pay_3001(db_client, db_session, authed):
    """他人订单支付 → 404/3001（越权-行级隔离）。"""
    merchant = await _seed_merchant(db_session)
    sku = await _seed_sku(db_session, merchant.id)
    data = await _create_order(
        db_client, authed["headers"], merchant.id, [{"sku_id": sku.id, "qty": 1}]
    )
    other = await _other_user(db_session, "smoke-23-other")
    resp = await db_client.post(f"/api/order/{data['order_id']}/pay", headers=other["headers"])
    assert resp.status_code == 404 and resp.json()["code"] == 3001


async def test_smoke_24_redeem_duplicate_5004(db_client, db_session, authed):
    """核销成功后重复核销 → 409/5004（幂等-防重复核销）。"""
    merchant = await _seed_merchant(db_session)
    data = await _paid_order(db_client, db_session, authed["headers"], merchant.id)
    listed = (await db_client.get("/api/order/list", headers=authed["headers"])).json()["data"]
    redeem_code = next(it for it in listed["items"] if it["order_no"] == data["order_no"])[
        "redeem_code"
    ]
    payload = {"redeem_code": redeem_code, "merchant_id": merchant.id}
    first = (
        await db_client.post(
            f"/api/order/{data['order_id']}/redeem", headers=authed["headers"], json=payload
        )
    ).json()
    assert first["code"] == 0
    second = await db_client.post(
        f"/api/order/{data['order_id']}/redeem", headers=authed["headers"], json=payload
    )
    assert second.status_code == 409 and second.json()["code"] == 5004


async def test_smoke_25_order_refund_flow(db_client, db_session, authed):
    """下单 → 支付回调 → 退款 → 订单 status=5（F1 新增退款链路）。"""
    merchant = await _seed_merchant(db_session)
    data = await _paid_order(db_client, db_session, authed["headers"], merchant.id)
    refunded = (
        await db_client.post(
            f"/api/order/{data['order_id']}/refund",
            headers=authed["headers"],
            json={"reason": "不想要了"},
        )
    ).json()
    assert refunded["code"] == 0 and refunded["data"]["refunded"] is True
    assert refunded["data"]["status"] == 5
    listed = (await db_client.get("/api/order/list?status=5", headers=authed["headers"])).json()[
        "data"
    ]
    assert any(it["order_no"] == data["order_no"] for it in listed["items"])


async def test_smoke_26_order_isolation_between_users(db_client, db_session, authed):
    """他人订单列表不可见（行级隔离）。"""
    merchant = await _seed_merchant(db_session)
    sku = await _seed_sku(db_session, merchant.id)
    await _create_order(db_client, authed["headers"], merchant.id, [{"sku_id": sku.id, "qty": 1}])
    other = await _other_user(db_session, "smoke-26-other")
    listed = (await db_client.get("/api/order/list", headers=other["headers"])).json()["data"]
    assert listed["page"]["total"] == 0


async def test_smoke_27_order_merchant_closed_5001(db_client, db_session, authed):
    """下单到停业商家 → 409/5001（异常态-商家停业）。"""
    merchant = await _seed_merchant(db_session, "停业店", status=0)
    sku = await _seed_sku(db_session, merchant.id)
    resp = await db_client.post(
        "/api/order",
        headers=authed["headers"],
        json={"merchant_id": merchant.id, "items": [{"sku_id": sku.id, "qty": 1}]},
    )
    assert resp.status_code == 409 and resp.json()["code"] == 5001


@pytest.mark.parametrize(
    ("variant", "code", "http"),
    [
        ("missing_merchant", 3001, 404),
        ("foreign_sku", 3001, 404),
        ("sku_off", 2001, 422),
        ("out_of_stock", 4001, 409),  # CD-09：库存不足 → 4001（05 文档 §8.6）
    ],
)
async def test_smoke_28_order_reject_variants(db_client, db_session, authed, variant, code, http):
    """下单非法组合：商家不存在 / SKU 非本店 / 已下架 / 库存不足 → 统一错误码。"""
    merchant = await _seed_merchant(db_session)
    sku = await _seed_sku(db_session, merchant.id, stock=1)
    payload = {"merchant_id": merchant.id, "items": [{"sku_id": sku.id, "qty": 1}]}
    if variant == "missing_merchant":
        payload["merchant_id"] = 999999
    elif variant == "foreign_sku":
        other_merchant = await _seed_merchant(db_session, "别家店")
        other_sku = await _seed_sku(db_session, other_merchant.id, "FD-002")
        payload["items"] = [{"sku_id": other_sku.id, "qty": 1}]
    elif variant == "sku_off":
        sku.status = 0
        await db_session.commit()
    elif variant == "out_of_stock":
        payload["items"] = [{"sku_id": sku.id, "qty": 2}]
    resp = await db_client.post("/api/order", headers=authed["headers"], json=payload)
    assert resp.status_code == http and resp.json()["code"] == code


async def test_smoke_29_notify_bad_sign_422(db_client, db_session, authed):
    """支付回调坏签名 → 422/2001（防篡改）。"""
    merchant = await _seed_merchant(db_session)
    sku = await _seed_sku(db_session, merchant.id)
    data = await _create_order(
        db_client, authed["headers"], merchant.id, [{"sku_id": sku.id, "qty": 1}]
    )
    resp = await db_client.post(
        "/api/order/notify",
        json={"order_no": data["order_no"], "amount": data["pay_amount"], "sign": "0" * 64},
    )
    assert resp.status_code == 422 and resp.json()["code"] == 2001


async def test_smoke_30_coupon_list_scoped(db_client, db_session, authed):
    """券列表：仅返回本人券（行级隔离）且字段完整。"""
    await _seed_coupon(db_session, authed["user_id"], scope=1)
    other = await _other_user(db_session, "smoke-30-other")
    await _seed_coupon(db_session, other["user_id"], scope=1)
    listed = (await db_client.get("/api/coupon/list", headers=authed["headers"])).json()["data"]
    assert listed["page"]["total"] == 1


# ---------------------------------------------------------------------------
# M4：社区 / 社交（SMK-31 ~ SMK-43）
# ---------------------------------------------------------------------------


async def test_smoke_31_post_create_list_detail(db_client, db_session, authed):
    """发动态 → 列表可见 → 详情可读。"""
    created = (
        await db_client.post(
            "/api/community/post", headers=authed["headers"], json={"content": "今天午餐打卡清蒸鱼"}
        )
    ).json()["data"]
    listed = (await db_client.get("/api/community/post/list", headers=authed["headers"])).json()[
        "data"
    ]
    assert any(p["id"] == created["id"] for p in listed["items"])
    detail = (
        await db_client.get(f"/api/community/post/{created['id']}", headers=authed["headers"])
    ).json()
    assert detail["code"] == 0 and detail["data"]["content"] == "今天午餐打卡清蒸鱼"


async def test_smoke_32_like_unlike_flow(db_client, db_session, authed):
    """点赞 → 取消赞 → like_count 归零。"""
    pid = (
        await db_client.post(
            "/api/community/post", headers=authed["headers"], json={"content": "打卡"}
        )
    ).json()["data"]["id"]
    liked = (
        await db_client.post(f"/api/community/post/{pid}/like", headers=authed["headers"])
    ).json()
    assert liked["code"] == 0 and liked["data"]["liked"] is True
    unliked = (
        await db_client.delete(f"/api/community/post/{pid}/like", headers=authed["headers"])
    ).json()
    assert unliked["code"] == 0 and unliked["data"]["like_count"] == 0


async def test_smoke_33_comment_flow(db_client, db_session, authed):
    """评论 → 评论列表可见 → 详情 comment_count 同步。"""
    pid = (
        await db_client.post(
            "/api/community/post", headers=authed["headers"], json={"content": "打卡"}
        )
    ).json()["data"]["id"]
    assert (
        await db_client.post(
            f"/api/community/post/{pid}/comment",
            headers=authed["headers"],
            json={"content": "加油！"},
        )
    ).json()["code"] == 0
    comments = (
        await db_client.get(f"/api/community/post/{pid}/comment/list", headers=authed["headers"])
    ).json()["data"]
    assert [c["content"] for c in comments["items"]] == ["加油！"]
    detail = (await db_client.get(f"/api/community/post/{pid}", headers=authed["headers"])).json()[
        "data"
    ]
    assert detail["comment_count"] == 1


async def test_smoke_34_post_delete_flow(db_client, db_session, authed):
    """删除动态 → 列表回空。"""
    pid = (
        await db_client.post(
            "/api/community/post", headers=authed["headers"], json={"content": "待删"}
        )
    ).json()["data"]["id"]
    deleted = (
        await db_client.delete(f"/api/community/post/{pid}", headers=authed["headers"])
    ).json()
    assert deleted["code"] == 0
    listed = (await db_client.get("/api/community/post/list", headers=authed["headers"])).json()[
        "data"
    ]
    assert listed["items"] == []


async def test_smoke_35_supervise_flow(db_client, db_session, authed):
    """监督搭子：匹配 → 提醒 → 互看记录。"""
    other = await _other_user(db_session, "smoke-35-b")
    sup = (
        await db_client.post(
            "/api/community/supervise/match",
            headers=authed["headers"],
            json={"partner_id": other["user_id"]},
        )
    ).json()["data"]
    assert sup["partner"]["id"] == other["user_id"]
    remind = (
        await db_client.post(
            f"/api/community/supervise/{sup['id']}/remind", headers=authed["headers"]
        )
    ).json()
    assert remind["code"] == 0 and remind["data"]["reminded"] is True
    records = (
        await db_client.get(
            f"/api/community/supervise/{sup['id']}/records", headers=authed["headers"]
        )
    ).json()
    assert records["code"] == 0 and records["data"]["partner"]["id"] == other["user_id"]


async def test_smoke_36_group_join_checkin_flow(db_client, db_session, authed):
    """兴趣社群：加入 → 打卡沉淀动态 → post_type=3 列表可见。"""
    group = await _seed_group(db_session, "smoke-36-社群")
    joined = (
        await db_client.post(f"/api/community/group/{group.id}/join", headers=authed["headers"])
    ).json()
    assert joined["code"] == 0 and joined["data"]["member_count"] == 1
    checkin = (
        await db_client.post(f"/api/community/group/{group.id}/checkin", headers=authed["headers"])
    ).json()["data"]
    assert checkin["checked"] is True and checkin["post_id"]
    listed = (
        await db_client.get("/api/community/post/list?post_type=3", headers=authed["headers"])
    ).json()["data"]
    assert checkin["post_id"] in [p["id"] for p in listed["items"]]


async def test_smoke_37_battle_create_join_list(db_client, db_session, authed):
    """约战：发起 → 加入 → 列表可见。"""
    created = (
        await db_client.post(
            "/api/community/battle",
            headers=authed["headers"],
            json={
                "title": "轻食约战",
                "sport_name": "轻食",
                "city": "上海",
                "meet_at": _future_iso(),
                "need_count": 2,
            },
        )
    ).json()["data"]
    joined = (
        await db_client.post(
            "/api/community/battle/join",
            headers=authed["headers"],
            json={"battle_id": created["id"]},
        )
    ).json()
    assert joined["code"] == 0 and joined["data"]["join_count"] == 2
    listed = (await db_client.get("/api/community/battle/list", headers=authed["headers"])).json()[
        "data"
    ]
    assert created["id"] in [b["id"] for b in listed["items"]]


async def test_smoke_38_challenge_join_detail_leaderboard(db_client, db_session, authed):
    """挑战赛：参加 → 详情 → 排行榜。"""
    challenge = await _seed_challenge(db_session, "smoke-38-挑战赛")
    joined = (
        await db_client.post(
            f"/api/community/challenge/{challenge.id}/join", headers=authed["headers"]
        )
    ).json()
    assert joined["code"] == 0 and joined["data"]["joined"] is True
    detail = (
        await db_client.get(f"/api/community/challenge/{challenge.id}", headers=authed["headers"])
    ).json()
    assert detail["code"] == 0
    board = (
        await db_client.get(
            f"/api/community/challenge/{challenge.id}/leaderboard", headers=authed["headers"]
        )
    ).json()
    assert board["code"] == 0 and isinstance(board["data"]["items"], list)


async def test_smoke_39_leaderboard_from_snapshot(db_client, db_session, authed):
    """热量控制榜：基于每日快照聚合，缺口大者排名高。"""
    other = await _other_user(db_session, "smoke-39-b")
    day = datetime.now(TZ).date()
    db_session.add_all(
        [
            DailySnapshot(user_id=authed["user_id"], snapshot_date=day, deficit=-300),
            DailySnapshot(user_id=other["user_id"], snapshot_date=day, deficit=-800),
        ]
    )
    await db_session.commit()
    board = (
        await db_client.get(
            f"/api/community/leaderboard?period_type=1&period_key={_today()}",
            headers=authed["headers"],
        )
    ).json()
    assert board["code"] == 0 and board["data"]["items"][0]["user"]["id"] == other["user_id"]


async def test_smoke_40_invite_bind_progress(db_client, db_session, authed):
    """邀请裂变（新口径）：生成邀请码 → 他人绑定 → 注册即有效、进度立即 +1。"""
    code = (await db_client.post("/api/invite", headers=authed["headers"], json={})).json()["data"][
        "invite_code"
    ]
    other = await _other_user(db_session, "smoke-40-b")
    bound = (
        await db_client.post("/api/invite", headers=other["headers"], json={"invite_code": code})
    ).json()
    assert bound["code"] == 0 and bound["data"]["bound"] is True
    progress = (await db_client.get("/api/invite/progress", headers=authed["headers"])).json()[
        "data"
    ]
    assert progress["invitee_count"] == 1  # 注册即有效，绑定即计数


async def test_smoke_41_experience_list(db_client, db_session, authed):
    """同款减友经验：仅 post_type=2 动态进入经验列表。"""
    await db_client.post(
        "/api/community/post",
        headers=authed["headers"],
        json={"content": "我的减脂经验", "post_type": 2, "title": "经验贴"},
    )
    await db_client.post(
        "/api/community/post", headers=authed["headers"], json={"content": "普通动态"}
    )
    listed = (
        await db_client.get("/api/community/experience/list", headers=authed["headers"])
    ).json()["data"]
    assert [it["content"] for it in listed["items"]] == ["我的减脂经验"]


async def test_smoke_42_anonymous_post(db_client, db_session, authed):
    """匿名发帖 → 列表隐藏作者身份（异常态-隐私态）。"""
    await db_client.post(
        "/api/community/post",
        headers=authed["headers"],
        json={"content": "匿名吐槽", "anonymous": True},
    )
    listed = (await db_client.get("/api/community/post/list", headers=authed["headers"])).json()[
        "data"
    ]
    assert listed["items"][0]["anonymous"] is True


async def test_smoke_43_post_non_owner_delete_forbidden(db_client, db_session, authed):
    """非作者删除动态 → 403/1002（越权）。"""
    pid = (
        await db_client.post(
            "/api/community/post", headers=authed["headers"], json={"content": "别人的"}
        )
    ).json()["data"]["id"]
    other = await _other_user(db_session, "smoke-43-b")
    resp = await db_client.delete(f"/api/community/post/{pid}", headers=other["headers"])
    assert resp.status_code == 403 and resp.json()["code"] == 1002


# ---------------------------------------------------------------------------
# 管理后台 + 内容审核（SMK-44 ~ SMK-50）
# ---------------------------------------------------------------------------


async def test_smoke_44_admin_login_and_merchant_audit(db_client, db_session, admin_authed):
    """管理后台：登录 → 商家审核通过（ADM 入驻闭环）。"""
    headers = await _admin_headers(db_client, admin_authed)
    merchant = await _seed_merchant(db_session, "待审店", audit_status=0)
    reviewed = (
        await db_client.post(
            f"/api/admin/merchants/{merchant.id}/audit", headers=headers, json={"audit_status": 1}
        )
    ).json()
    assert reviewed["code"] == 0 and reviewed["data"]["audit_status"] == 1
    listed = (await db_client.get("/api/admin/merchants", headers=headers)).json()
    assert listed["code"] == 0


async def test_smoke_45_admin_sku_pricing_flow(db_client, db_session, admin_authed):
    """管理后台：选品定价（合法区间通过 / 越界 422）。"""
    headers = await _admin_headers(db_client, admin_authed)
    merchant = await _seed_merchant(db_session, "定价店")
    ok = (
        await db_client.post(
            "/api/admin/merchant-skus",
            headers=headers,
            json={"merchant_id": merchant.id, "catalog_id": 1, "price": 25.0},
        )
    ).json()
    assert ok["code"] == 0 and ok["data"]["min_price"] <= 25.0 <= ok["data"]["max_price"]
    bad = await db_client.post(
        "/api/admin/merchant-skus",
        headers=headers,
        json={"merchant_id": merchant.id, "catalog_id": 1, "price": 999.0},
    )
    assert bad.status_code == 400 and bad.json()["code"] == 2001


async def test_smoke_46_admin_coupon_pool_grant_to_user(
    db_client, db_session, admin_authed, authed
):
    """管理后台：建券池 → 发放给用户 → 用户券列表可见（运营→C 端串联）。"""
    headers = await _admin_headers(db_client, admin_authed)
    pool = (
        await db_client.post(
            "/api/admin/coupon-pools",
            headers=headers,
            json={"name": "补贴池", "type": 3, "scope": 4, "amount": 8, "total_count": 5},
        )
    ).json()["data"]
    granted = (
        await db_client.post(
            f"/api/admin/coupon-pools/{pool['id']}/grant",
            headers=headers,
            json={"pool_id": pool["id"], "user_id": authed["user_id"], "count": 1},
        )
    ).json()
    assert granted["code"] == 0 and granted["data"]["granted_count"] >= 1
    coupons = (await db_client.get("/api/coupon/list", headers=authed["headers"])).json()["data"]
    assert coupons["page"]["total"] >= 1


async def test_smoke_47_admin_orders_and_dashboard(db_client, db_session, admin_authed, authed):
    """管理后台：订单监控 + 运营看板（ADM 数据链路）。"""
    headers = await _admin_headers(db_client, admin_authed)
    merchant = await _seed_merchant(db_session)
    sku = await _seed_sku(db_session, merchant.id)
    await _create_order(db_client, authed["headers"], merchant.id, [{"sku_id": sku.id, "qty": 1}])
    orders = (await db_client.get("/api/admin/orders", headers=headers)).json()
    assert orders["code"] == 0 and orders["data"]["page"]["total"] >= 1
    dashboard = (await db_client.get("/api/admin/dashboard", headers=headers)).json()
    assert dashboard["code"] == 0


async def test_smoke_48_content_audit_post_approve_flow(
    db_client, db_session, admin_authed, authed
):
    """内容审核：违规动态入队 → 后台审核通过 → 动态对外可见（社区↔ADM 串联）。"""
    created = (
        await db_client.post(
            "/api/community/post", headers=authed["headers"], json={"content": "这条含违规词的动态"}
        )
    ).json()["data"]
    assert created["audit_status"] == 0
    headers = await _admin_headers(db_client, admin_authed)
    queue = (await db_client.get("/api/admin/audit/list?status=0", headers=headers)).json()["data"]
    review_id = next(it["id"] for it in queue["items"] if it["target_type"] == 1)
    assert (
        await db_client.post(
            f"/api/admin/audit/{review_id}/review", headers=headers, json={"status": 1}
        )
    ).json()["code"] == 0
    listed = (await db_client.get("/api/community/post/list", headers=authed["headers"])).json()[
        "data"
    ]
    assert created["id"] in [p["id"] for p in listed["items"]]


async def test_smoke_49_content_audit_comment_reject_flow(
    db_client, db_session, admin_authed, authed
):
    """内容审核：违规评论入队 → 驳回 → 评论不展示。"""
    pid = (
        await db_client.post(
            "/api/community/post", headers=authed["headers"], json={"content": "正常动态"}
        )
    ).json()["data"]["id"]
    await db_client.post(
        f"/api/community/post/{pid}/comment",
        headers=authed["headers"],
        json={"content": "评论含违规词"},
    )
    headers = await _admin_headers(db_client, admin_authed)
    queue = (await db_client.get("/api/admin/audit/list?status=0", headers=headers)).json()["data"]
    review_id = next(it["id"] for it in queue["items"] if it["target_type"] == 2)
    await db_client.post(
        f"/api/admin/audit/{review_id}/review",
        headers=headers,
        json={"status": 2, "reason": "驳回"},
    )
    comments = (
        await db_client.get(f"/api/community/post/{pid}/comment/list", headers=authed["headers"])
    ).json()["data"]
    assert comments["items"] == []


async def test_smoke_50_track_anonymous_and_token(db_client, db_session, authed):
    """埋点：匿名上报与带 token 关联用户均受理（F3 核心指标入口）。"""
    anon = (
        await db_client.post(
            "/api/track", json={"events": [{"event": "scan_in"}, {"event": "login"}]}
        )
    ).json()
    assert anon["code"] == 0 and anon["data"]["accepted"] == 2
    authed_report = (
        await db_client.post(
            "/api/track", headers=authed["headers"], json={"events": [{"event": "meal_photo"}]}
        )
    ).json()
    assert authed_report["code"] == 0 and authed_report["data"]["accepted"] == 1


# ---------------------------------------------------------------------------
# 补充：鉴权/校验/异常态（SMK-51 ~ SMK-55）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("post", "/api/order", {"json": {"merchant_id": 1, "items": [{"sku_id": 1, "qty": 1}]}}),
        ("post", "/api/community/post", {"json": {"content": "x"}}),
        ("get", "/api/account/today", {}),
        ("get", "/api/order/list", {}),
    ],
)
async def test_smoke_51_core_endpoints_require_auth(db_client, db_session, method, path, kwargs):
    """核心写/读接口未带 token → 401/1001（统一鉴权入口）。"""
    resp = await getattr(db_client, method)(path, **kwargs)
    assert resp.status_code == 401 and resp.json()["code"] == 1001


async def test_smoke_52_body_profile_validation_422(db_client, db_session, authed):
    """建档非法参数（身高越界）→ 422/2001（异常态-参数校验）。"""
    resp = await db_client.post(
        "/api/body-profile",
        headers=authed["headers"],
        json={
            "gender": 1,
            "height_cm": 999,
            "current_weight": 70,
            "target_type": 1,
            "activity_level": 3,
        },
    )
    assert resp.status_code == 422 and resp.json()["code"] == 2001


async def test_smoke_53_meal_not_found_404(db_client, db_session, authed):
    """编辑不存在饮食记录 → 404/3001（异常态-资源不存在）。"""
    resp = await db_client.put(
        "/api/meal/999999", headers=authed["headers"], json={"amount_g": 100}
    )
    assert resp.status_code == 404 and resp.json()["code"] == 3001


async def test_smoke_54_track_validation_422(db_client, db_session):
    """埋点空事件列表 → 422/2001（异常态-参数校验）。"""
    resp = await db_client.post("/api/track", json={"events": []})
    assert resp.status_code == 422 and resp.json()["code"] == 2001


async def test_smoke_55_full_journey_login_to_redeem(db_client, db_session):
    """全链路一气呵成：登录→建档→记餐→查账户→浏览商家→下单→支付→核销。"""
    session = await _login(db_client, "smoke-55")
    headers = session["headers"]
    await _build_profile(db_client, headers)
    food = await _seed_food(db_session, "全链路食物", 200.0)
    await db_client.post(
        "/api/meal",
        headers=headers,
        json={"meal_type": 2, "food_id": food.id, "amount_g": 100, "source": 1},
    )
    today = (await db_client.get("/api/account/today", headers=headers)).json()["data"]
    assert today["intake"] == 200.0

    merchant = await _seed_merchant(db_session, "全链路店", lat=31.2304, lng=121.4737)
    await _seed_sku(db_session, merchant.id, "FD-001", price=28.0)
    listed = (
        await db_client.get(
            "/api/merchant/list", headers=headers, params={"lat": 31.223, "lng": 121.482}
        )
    ).json()["data"]
    merchant_id = next(it["id"] for it in listed["items"] if it["id"] == merchant.id)

    detail = (await db_client.get(f"/api/merchant/{merchant_id}", headers=headers)).json()["data"]
    sku_id = detail["skus"][0]["id"]
    order = await _create_order(db_client, headers, merchant_id, [{"sku_id": sku_id, "qty": 1}])
    assert (await _notify(db_client, order["order_no"], order["pay_amount"])).json()["code"] == 0
    orders = (await db_client.get("/api/order/list", headers=headers)).json()["data"]
    redeem_code = next(
        it["redeem_code"] for it in orders["items"] if it["order_no"] == order["order_no"]
    )
    redeemed = (
        await db_client.post(
            f"/api/order/{order['order_id']}/redeem",
            headers=headers,
            json={"redeem_code": redeem_code, "merchant_id": merchant_id},
        )
    ).json()
    assert redeemed["code"] == 0 and redeemed["data"]["status"] == "redeemed"
