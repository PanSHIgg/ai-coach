"""商家自助后台测试（G11 独立商家 token 域）：登录/信息/选品定价/上下架/订单/核销/看板/比价。

真实 DB（db_client + db_session + authed）；sku_catalog 为种子参照表（不清空），
比价用例直接引用其 id/区间。商家账号（merchant_account）直接落库，口令用
`core.security.hash_password`（本仓库未安装 passlib/bcrypt；verifier 兼容 bcrypt 前缀）。
"""

import uuid

import pytest
from geoalchemy2 import WKTElement
from sqlalchemy import select

from app.core.security import hash_password
from app.models import (
    CouponPool,
    Merchant,
    MerchantAccount,
    MerchantSku,
    Order,
    RedeemLog,
    SkuCatalog,
)

_LAT, _LNG = 31.2304, 121.4737  # 上海人民广场附近


# ---------------------------------------------------------------------------
# 造数助手
# ---------------------------------------------------------------------------


async def _catalog_id(db_session, code="FD-001") -> int:
    return await db_session.scalar(select(SkuCatalog.id).where(SkuCatalog.code == code))


async def _seed_merchant(
    db_session,
    name="自助一号店",
    *,
    lat=None,
    lng=None,
    status=1,
    audit_status=1,
    rating=4.8,
    contribution_points=0,
) -> Merchant:
    geo = (
        WKTElement(f"POINT({lng} {lat})", srid=4326)
        if lat is not None and lng is not None
        else None
    )
    m = Merchant(
        name=name,
        category="轻食",
        address="XX路1号",
        geo=geo,
        rating=rating,
        status=status,
        audit_status=audit_status,
        contribution_points=contribution_points,
    )
    db_session.add(m)
    await db_session.flush()
    return m


async def _seed_account(
    db_session, merchant_id, *, username=None, password="Shop@123456", status=1
) -> MerchantAccount:
    acc = MerchantAccount(
        merchant_id=merchant_id,
        username=username or f"shop-{uuid.uuid4().hex[:8]}",
        password_hash=hash_password(password),
        status=status,
    )
    db_session.add(acc)
    await db_session.commit()
    return acc


async def _seed_sku(db_session, merchant_id, catalog_id, *, price=25.0, stock=-1, status=1):
    ms = MerchantSku(
        merchant_id=merchant_id, catalog_id=catalog_id, price=price, stock=stock, status=status
    )
    db_session.add(ms)
    await db_session.commit()
    return ms


async def _seed_order(db_session, merchant_id, *, status=2, amount=25.0, user_id=None):
    o = Order(
        order_no=f"DD{uuid.uuid4().hex[:12].upper()}",
        user_id=user_id,
        merchant_id=merchant_id,
        total_amount=amount,
        pay_amount=amount,
        status=status,
    )
    db_session.add(o)
    await db_session.commit()
    return o


async def _login(db_client, username: str, password: str):
    return await db_client.post(
        "/api/merchant/login", json={"username": username, "password": password}
    )


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _merchant_token(db_client, db_session, **mkw) -> tuple[Merchant, str]:
    """造商家 + 账号并登录，返回 (merchant, token)。"""
    m = await _seed_merchant(db_session, **mkw)
    acc = await _seed_account(db_session, m.id)
    r = await _login(db_client, acc.username, "Shop@123456")
    assert r.status_code == 200, r.text
    return m, r.json()["data"]["token"]


# ---------------------------------------------------------------------------
# 登录
# ---------------------------------------------------------------------------


async def test_login_success_returns_token_and_updates_last_login(
    db_client, db_session
):
    m = await _seed_merchant(db_session)
    acc = await _seed_account(db_session, m.id)

    r = await _login(db_client, acc.username, "Shop@123456")
    assert r.status_code == 200 and r.json()["code"] == 0
    data = r.json()["data"]
    assert data["merchant_id"] == m.id and data["name"] == m.name
    assert data["token"] and data["expires_in"] == 7200  # JWT_ACCESS_EXPIRE_HOURS=2

    # 商家 token 可访问受保护端点
    r2 = await db_client.get("/api/merchant/me", headers=_auth(data["token"]))
    assert r2.status_code == 200 and r2.json()["data"]["id"] == m.id

    refreshed = (
        await db_session.execute(
            select(MerchantAccount)
            .where(MerchantAccount.id == acc.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert refreshed.last_login_at is not None


@pytest.mark.parametrize("variant", ["wrong_password", "unknown_user", "disabled_account"])
async def test_login_failure_unified_1001(db_client, db_session, variant):
    """口令错/账号不存在/账号停用 → 统一 1001（不泄露账号是否存在）。"""
    m = await _seed_merchant(db_session)
    acc = await _seed_account(db_session, m.id)

    if variant == "wrong_password":
        r = await _login(db_client, acc.username, "Wrong@123456")
    elif variant == "unknown_user":
        r = await _login(db_client, "no-such-account", "Whatever@123")
    else:
        acc.status = 0
        await db_session.commit()
        r = await _login(db_client, acc.username, "Shop@123456")

    assert r.status_code == 401 and r.json()["code"] == 1001


@pytest.mark.parametrize(
    "method,url,json",
    [
        ("GET", "/api/merchant/me", None),
        ("GET", "/api/merchant/skus", None),
        ("PUT", "/api/merchant/skus", {"items": [{"sku_id": 1, "price": 20.0, "listed": True}]}),
        ("POST", "/api/merchant/sku/1/toggle", None),
        ("GET", "/api/merchant/orders", None),
        ("POST", "/api/merchant/order/1/redeem", None),
        ("GET", "/api/merchant/stats", None),
    ],
)
async def test_self_endpoints_require_merchant_token(db_client, method, url, json):
    """未带商家 token 访问任一受保护端点 → 401/1001（逐 (method,url) 独立成例，fail 可定位）。"""
    r = await db_client.request(method, url, json=json)
    assert r.status_code == 401, f"{method} {url}"
    assert r.json()["code"] == 1001, f"{method} {url}"


async def test_client_user_token_rejected_on_merchant_api(db_client, authed):
    """C 端 user token 打商家自助端点 → 401/1001（域隔离）。"""
    r = await db_client.get("/api/merchant/me", headers=authed["headers"])
    assert r.status_code == 401 and r.json()["code"] == 1001


# ---------------------------------------------------------------------------
# 信息 / 选品定价
# ---------------------------------------------------------------------------


async def test_me_returns_merchant_info(db_client, db_session):
    m, token = await _merchant_token(db_client, db_session, name="信息店", rating=4.3)
    r = await db_client.get("/api/merchant/me", headers=_auth(token))
    assert r.status_code == 200 and r.json()["code"] == 0
    data = r.json()["data"]
    assert data["id"] == m.id and data["name"] == "信息店"
    assert data["status"] == 1 and data["audit_status"] == 1
    assert data["rating"] == 4.3 and data["partner_level"] == 0
    assert {"category", "address", "phone"} <= set(data)


async def test_skus_list_joins_catalog_range(db_client, db_session):
    cid = await _catalog_id(db_session)
    m, token = await _merchant_token(db_client, db_session)
    ms = await _seed_sku(db_session, m.id, cid, price=25.0, stock=9, status=1)

    r = await db_client.get("/api/merchant/skus", headers=_auth(token))
    assert r.status_code == 200 and r.json()["code"] == 0
    items = r.json()["data"]["items"]
    assert len(items) == 1
    item = items[0]
    assert item["sku_id"] == ms.id and item["catalog_id"] == cid
    assert item["catalog_code"] == "FD-001" and item["catalog_name"]
    assert item["price"] == 25.0 and item["min_price"] == 19.0 and item["max_price"] == 32.0
    assert item["stock"] == 9 and item["status"] == 1


@pytest.mark.parametrize("price", [18.99, 32.01])
async def test_update_sku_price_out_of_range_400(db_client, db_session, price):
    """定价越出目录区间 [19, 32] → 2001/400，且不落库。"""
    cid = await _catalog_id(db_session)
    m, token = await _merchant_token(db_client, db_session)
    ms = await _seed_sku(db_session, m.id, cid, price=25.0)

    r = await db_client.put(
        "/api/merchant/skus",
        headers=_auth(token),
        json={"items": [{"sku_id": ms.id, "price": price, "listed": True}]},
    )
    assert r.status_code == 400
    body = r.json()
    assert body["code"] == 2001 and "19" in body["message"] and "32" in body["message"]

    kept = (
        await db_session.execute(
            select(MerchantSku).where(MerchantSku.id == ms.id).execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert kept.price == 25.0  # 未修改


async def test_update_sku_price_and_listed(db_client, db_session):
    """区间内定价 + listed=false → 价格更新且下架。"""
    cid = await _catalog_id(db_session)
    m, token = await _merchant_token(db_client, db_session)
    ms = await _seed_sku(db_session, m.id, cid, price=25.0, status=1)

    r = await db_client.put(
        "/api/merchant/skus",
        headers=_auth(token),
        json={"items": [{"sku_id": ms.id, "price": 28.0, "listed": False}]},
    )
    assert r.status_code == 200 and r.json()["code"] == 0
    item = r.json()["data"]["items"][0]
    assert item["price"] == 28.0 and item["status"] == 0

    kept = (
        await db_session.execute(
            select(MerchantSku).where(MerchantSku.id == ms.id).execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert kept.price == 28.0 and kept.status == 0


async def test_toggle_sku_and_not_found(db_client, db_session):
    """上/下架切换（1→0→1）；不存在/他店 SKU → 3001。"""
    cid = await _catalog_id(db_session)
    m, token = await _merchant_token(db_client, db_session)
    ms = await _seed_sku(db_session, m.id, cid, status=1)

    r = await db_client.post(f"/api/merchant/sku/{ms.id}/toggle", headers=_auth(token))
    assert r.status_code == 200 and r.json()["data"] == {"sku_id": ms.id, "status": 0}
    r = await db_client.post(f"/api/merchant/sku/{ms.id}/toggle", headers=_auth(token))
    assert r.json()["data"]["status"] == 1

    r = await db_client.post("/api/merchant/sku/99999/toggle", headers=_auth(token))
    assert r.status_code == 404 and r.json()["code"] == 3001


# ---------------------------------------------------------------------------
# 订单 / 核销
# ---------------------------------------------------------------------------


async def test_orders_list_pagination_and_status_filter(db_client, db_session):
    m, token = await _merchant_token(db_client, db_session)
    other = await _seed_merchant(db_session, "别家店")
    await _seed_order(db_session, m.id, status=2, amount=30.0)
    await _seed_order(db_session, m.id, status=3, amount=20.0)
    await _seed_order(db_session, other.id, status=2, amount=40.0)  # 他店不可见

    r = await db_client.get("/api/merchant/orders", headers=_auth(token))
    assert r.status_code == 200 and r.json()["code"] == 0
    data = r.json()["data"]
    assert data["page"]["total"] == 2  # 行级隔离
    assert all(it["order_no"] for it in data["items"])

    r = await db_client.get("/api/merchant/orders?status=3", headers=_auth(token))
    data = r.json()["data"]
    assert data["page"]["total"] == 1 and data["items"][0]["status"] == 3


async def test_orders_list_fills_redeemed_at_from_log(db_client, db_session):
    """已核销订单列表回填真实核销时间（取自 redeem_log 最近一次成功记录）。"""
    m, token = await _merchant_token(db_client, db_session)
    order = await _seed_order(db_session, m.id, status=3, amount=25.0)
    db_session.add(RedeemLog(order_id=order.id, merchant_id=m.id, result=1))
    await db_session.commit()

    r = await db_client.get("/api/merchant/orders", headers=_auth(token))
    assert r.status_code == 200 and r.json()["code"] == 0
    item = r.json()["data"]["items"][0]
    assert item["id"] == order.id
    assert item["redeemed_at"] is not None


async def test_redeem_success_then_duplicate_5004(db_client, db_session):
    m, token = await _merchant_token(db_client, db_session)
    order = await _seed_order(db_session, m.id, status=2, amount=25.0)

    r1 = await db_client.post(f"/api/merchant/order/{order.id}/redeem", headers=_auth(token))
    assert r1.status_code == 200 and r1.json()["code"] == 0
    d = r1.json()["data"]
    assert d["order_id"] == order.id and d["status"] == 3 and d["redeemed_at"]
    assert (
        await db_session.scalar(select(Order.status).where(Order.id == order.id))
    ) == 3

    # 失败/成功均留痕
    logs = (
        (await db_session.execute(select(RedeemLog).where(RedeemLog.order_id == order.id)))
        .scalars()
        .all()
    )
    assert len(logs) == 1 and logs[0].result == 1

    r2 = await db_client.post(f"/api/merchant/order/{order.id}/redeem", headers=_auth(token))
    assert r2.status_code == 409 and r2.json()["code"] == 5004  # 核销码一次性


async def test_redeem_foreign_order_3001(db_client, db_session):
    m, token = await _merchant_token(db_client, db_session)
    other = await _seed_merchant(db_session, "他人店")
    order = await _seed_order(db_session, other.id, status=2)

    r = await db_client.post(f"/api/merchant/order/{order.id}/redeem", headers=_auth(token))
    assert r.status_code == 404 and r.json()["code"] == 3001
    assert order.status == 2  # 未被核销


# ---------------------------------------------------------------------------
# 看板
# ---------------------------------------------------------------------------


async def test_stats_aggregation(db_client, db_session):
    cid = await _catalog_id(db_session)
    m, token = await _merchant_token(db_client, db_session, contribution_points=7)
    await _seed_sku(db_session, m.id, cid, status=1)
    await _seed_sku(db_session, m.id, await _catalog_id(db_session, "FD-002"), status=0)
    await _seed_order(db_session, m.id, status=2, amount=30.0)
    await _seed_order(db_session, m.id, status=3, amount=20.0)
    await _seed_order(db_session, m.id, status=1, amount=10.0)  # 待支付不计 GMV

    r = await db_client.get("/api/merchant/stats", headers=_auth(token))
    assert r.status_code == 200 and r.json()["code"] == 0
    d = r.json()["data"]
    assert d["merchant_id"] == m.id
    assert d["order_count"] == 3 and d["redeem_count"] == 1
    assert d["gmv"] == 50.0  # 30 + 20
    assert d["sku_count"] == 1  # 仅 status=1
    assert d["contribution_points"] == 7


# ---------------------------------------------------------------------------
# 比价（C 端）
# ---------------------------------------------------------------------------


async def test_compare_ordering_by_price_and_coupon(db_client, db_session, authed):
    """按券后实付价排序；券抵扣（coupon_amount）参与排序并能翻转名次。"""
    cid = await _catalog_id(db_session)
    m_high = await _seed_merchant(db_session, "高价店", lat=_LAT, lng=_LNG, rating=4.9)
    m_low = await _seed_merchant(db_session, "低价店", lat=_LAT + 0.001, lng=_LNG, rating=4.0)
    await _seed_sku(db_session, m_high.id, cid, price=30.0)
    await _seed_sku(db_session, m_low.id, cid, price=20.0)
    q_lat, q_lng = _LAT - 0.01, _LNG - 0.01  # 与两店均不重合 → distance > 0

    # 无券：按价格升序
    r = await db_client.get(
        "/api/merchant/compare",
        headers=authed["headers"],
        params={"sku_id": cid, "lat": q_lat, "lng": q_lng},
    )
    assert r.status_code == 200 and r.json()["code"] == 0
    items = r.json()["data"]["items"]
    assert [it["merchant_id"] for it in items] == [m_low.id, m_high.id]
    assert all(it["sku_name"] and it["distance"] > 0 for it in items)

    # 给高价店挂 15 元券 → 券后 15 < 20，名次翻转
    db_session.add(
        CouponPool(
            name="满减15",
            type=1,
            scope=1,
            amount=15.0,
            total_count=-1,
            granted_count=0,
            merchant_id=m_high.id,
            status=1,
        )
    )
    await db_session.commit()

    r = await db_client.get(
        "/api/merchant/compare",
        headers=authed["headers"],
        params={"sku_id": cid, "lat": q_lat, "lng": q_lng},
    )
    items = r.json()["data"]["items"]
    assert [it["merchant_id"] for it in items] == [m_high.id, m_low.id]
    assert items[0]["coupon_amount"] == 15.0 and items[0]["price"] == 30.0
    assert items[1]["coupon_amount"] == 0.0