"""BE9 管理 API 集成测试：登录/审核/选品定价/券池/发放/订单监控。

均走真实 PostgreSQL（db_client + db_session，DATABASE_URL 指向隔离库）；
token 一律经 /api/admin/login 获取（与 C 端 JWT 体系解耦）。
"""

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models import AdminUser, Coupon, Merchant, MerchantSku, Order, User

# sku_catalog 为种子参照数据（FD-001: ¥19-¥32 ...），测试直接引用其 id/区间


async def _login(db_client: AsyncClient, cred: dict) -> dict:
    r = await db_client.post("/api/admin/login", json=cred)
    assert r.status_code == 200, r.text
    assert r.json()["code"] == 0
    return r.json()["data"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _create_merchant(db_session: AsyncSession, name: str, **kw) -> Merchant:
    m = Merchant(name=name, category="轻食", address=f"{name}路1号", **kw)
    db_session.add(m)
    await db_session.commit()
    return m


async def _create_role3_admin(db_session: AsyncSession, merchant_id: int) -> dict:
    """造 role=3 商家账号并返回凭据。"""
    cred = {"username": f"shop-{merchant_id}", "password": "Shop@123456"}
    db_session.add(
        AdminUser(
            username=cred["username"],
            password_hash=hash_password(cred["password"]),
            role=3,
            merchant_id=merchant_id,
        )
    )
    await db_session.commit()
    return cred


# ---- 登录 ----


async def test_login_success_and_wrong_password(db_client: AsyncClient, admin_authed: dict):
    # 成功：返回 token/role/username，token 可访问 admin 接口
    data = await _login(db_client, admin_authed)
    assert data["token"] and data["role"] == 1
    assert data["username"] == admin_authed["username"]
    r = await db_client.get(
        "/api/admin/merchants", headers=_auth(data["token"])
    )
    assert r.status_code == 200

    # 密码错 / 用户不存在 -> 1001/401
    for body in (
        {"username": admin_authed["username"], "password": "Wrong@123456"},
        {"username": "no-such-admin", "password": "Whatever@123"},
    ):
        r = await db_client.post("/api/admin/login", json=body)
        assert r.status_code == 401
        assert r.json()["code"] == 1001


async def test_admin_endpoints_require_token(db_client: AsyncClient):
    """未带 token 访问任一 admin 接口 -> 1001/401。"""
    cases = [
        ("GET", "/api/admin/merchants", None),
        ("POST", "/api/admin/merchants/1/audit", {"audit_status": 1}),
        ("POST", "/api/admin/merchant-skus", {"merchant_id": 1, "catalog_id": 1, "price": 25}),
        ("POST", "/api/admin/merchant-skus/1/status", {"status": 0}),
        ("GET", "/api/admin/coupon-pools", None),
        ("POST", "/api/admin/coupon-pools/1/grant", {"pool_id": 1, "user_id": 1}),
        ("GET", "/api/admin/orders", None),
        ("GET", "/api/admin/dashboard", None),
    ]
    for method, url, json in cases:
        r = await db_client.request(method, url, json=json)
        assert r.status_code == 401, url
        assert r.json()["code"] == 1001, url


# ---- P0-1 token 域隔离（dom claim）----


async def test_c_user_token_rejected_on_admin_api(
    db_client: AsyncClient, db_session: AsyncSession, authed: dict
):
    """C 端 user token（无 dom claim）打 admin 接口 -> 401/1001。"""
    r = await db_client.get("/api/admin/merchants", headers=authed["headers"])
    assert r.status_code == 401
    assert r.json()["code"] == 1001


async def test_admin_token_rejected_on_client_api(
    db_client: AsyncClient, db_session: AsyncSession, authed: dict, admin_authed: dict
):
    """admin token（dom=admin）打 C 端接口 -> 401/1001（防反向冒充 C 端用户）。"""
    token = (await _login(db_client, admin_authed))["token"]
    r = await db_client.get("/api/coupon/list", headers=_auth(token))
    assert r.status_code == 401
    assert r.json()["code"] == 1001


# ---- P1-4 管理侧标准目录 ----


async def test_admin_sku_catalog(db_client: AsyncClient, admin_authed: dict):
    """GET /api/admin/sku-catalog：admin token 200 返回 5 行种子；category 过滤生效。"""
    token = (await _login(db_client, admin_authed))["token"]
    r = await db_client.get("/api/admin/sku-catalog", headers=_auth(token))
    assert r.status_code == 200 and r.json()["code"] == 0
    items = r.json()["data"]["items"]
    assert len(items) == 5
    assert {it["code"] for it in items} == {"FD-001", "FD-002", "FD-003", "SP-001", "SP-002"}

    r2 = await db_client.get(
        "/api/admin/sku-catalog", params={"category": "标准减脂餐"}, headers=_auth(token)
    )
    assert r2.status_code == 200
    assert len(r2.json()["data"]["items"]) == 3


# ---- 商家审核 ----


async def test_audit_merchant_approve_and_reject(
    db_session: AsyncSession, db_client: AsyncClient, admin_authed: dict
):
    token = (await _login(db_client, admin_authed))["token"]
    m1 = await _create_merchant(db_session, "待审店A")
    m2 = await _create_merchant(db_session, "待审店B")

    # 通过
    r = await db_client.post(
        f"/api/admin/merchants/{m1.id}/audit", json={"audit_status": 1}, headers=_auth(token)
    )
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["audit_status"] == 1 and body["id"] == m1.id

    # 驳回：回显 reason
    r = await db_client.post(
        f"/api/admin/merchants/{m2.id}/audit",
        json={"audit_status": 2, "reason": "资质不全"},
        headers=_auth(token),
    )
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["audit_status"] == 2 and body["audit_reason"] == "资质不全"


async def test_audit_denied_for_merchant_role(
    db_session: AsyncSession, db_client: AsyncClient
):
    m = await _create_merchant(db_session, "越权目标店")
    cred = await _create_role3_admin(db_session, m.id)
    token = (await _login(db_client, cred))["token"]
    r = await db_client.post(
        f"/api/admin/merchants/{m.id}/audit", json={"audit_status": 1}, headers=_auth(token)
    )
    assert r.status_code == 403
    assert r.json()["code"] == 1002


# ---- 选品定价 ----


async def test_upsert_sku_create_then_update(
    db_session: AsyncSession, db_client: AsyncClient, admin_authed: dict
):
    token = (await _login(db_client, admin_authed))["token"]
    m = await _create_merchant(db_session, "选品店")

    # 首次：插入，回显目录区间/编码/名称
    r = await db_client.post(
        "/api/admin/merchant-skus",
        json={"merchant_id": m.id, "catalog_id": 1, "price": 25.0},
        headers=_auth(token),
    )
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["catalog_code"] == "FD-001" and body["catalog_name"]
    assert body["price"] == 25.0 and body["min_price"] == 19.0 and body["max_price"] == 32.0
    assert body["stock"] == -1 and body["status"] == 1

    # 重复：(merchant_id, catalog_id) 已存在 -> 更新而非插入
    r = await db_client.post(
        "/api/admin/merchant-skus",
        json={"merchant_id": m.id, "catalog_id": 1, "price": 28.0, "stock": 5, "status": 0},
        headers=_auth(token),
    )
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["id"] == r.json()["data"]["id"] and body["price"] == 28.0
    assert body["stock"] == 5 and body["status"] == 0
    sku_count = await db_session.scalar(
        select(func.count())
        .select_from(MerchantSku)
        .where(MerchantSku.merchant_id == m.id, MerchantSku.catalog_id == 1)
    )
    assert sku_count == 1


async def test_upsert_sku_price_out_of_range(
    db_session: AsyncSession, db_client: AsyncClient, admin_authed: dict
):
    token = (await _login(db_client, admin_authed))["token"]
    m = await _create_merchant(db_session, "越界店")
    for price in (18.99, 32.01):  # 低于/高于 FD-001 区间 [19, 32]
        r = await db_client.post(
            "/api/admin/merchant-skus",
            json={"merchant_id": m.id, "catalog_id": 1, "price": price},
            headers=_auth(token),
        )
        assert r.status_code == 422, price
        body = r.json()
        assert body["code"] == 2001
        assert "19" in body["message"] and "32" in body["message"]


async def test_upsert_sku_not_found(
    db_session: AsyncSession, db_client: AsyncClient, admin_authed: dict
):
    token = (await _login(db_client, admin_authed))["token"]
    m = await _create_merchant(db_session, "孤儿店")
    cases = [
        {"merchant_id": 99999, "catalog_id": 1, "price": 25.0},  # 商家不存在
        {"merchant_id": m.id, "catalog_id": 99999, "price": 25.0},  # 目录不存在
    ]
    for body in cases:
        r = await db_client.post("/api/admin/merchant-skus", json=body, headers=_auth(token))
        assert r.status_code == 404, body
        assert r.json()["code"] == 3001


async def test_sku_status_update_and_404(
    db_session: AsyncSession, db_client: AsyncClient, admin_authed: dict
):
    token = (await _login(db_client, admin_authed))["token"]
    m = await _create_merchant(db_session, "上下架店")
    r = await db_client.post(
        "/api/admin/merchant-skus",
        json={"merchant_id": m.id, "catalog_id": 2, "price": 30.0},
        headers=_auth(token),
    )
    sku_id = r.json()["data"]["id"]

    # 下架 -> 再上架
    for status, expect in ((0, 0), (1, 1)):
        r = await db_client.post(
            f"/api/admin/merchant-skus/{sku_id}/status",
            json={"status": status},
            headers=_auth(token),
        )
        assert r.status_code == 200
        assert r.json()["data"]["status"] == expect

    # 不存在 -> 3001/404
    r = await db_client.post(
        "/api/admin/merchant-skus/99999/status", json={"status": 0}, headers=_auth(token)
    )
    assert r.status_code == 404 and r.json()["code"] == 3001


# ---- 券池 ----


async def test_coupon_pool_create_and_list(
    db_session: AsyncSession, db_client: AsyncClient, admin_authed: dict
):
    token = (await _login(db_client, admin_authed))["token"]
    r = await db_client.post(
        "/api/admin/coupon-pools",
        json={"name": "新人满减券", "type": 1, "scope": 4, "amount": 10, "total_count": 5},
        headers=_auth(token),
    )
    assert r.status_code == 200
    pool = r.json()["data"]
    assert pool["id"] > 0 and pool["granted_count"] == 0 and pool["total_count"] == 5

    r = await db_client.get("/api/admin/coupon-pools", headers=_auth(token))
    assert r.status_code == 200
    page = r.json()["data"]
    assert page["page"]["total"] == 1
    assert any(p["id"] == pool["id"] for p in page["items"])


async def test_coupon_pools_denied_for_merchant_role(
    db_session: AsyncSession, db_client: AsyncClient
):
    """P1-1：role=3 商家账号读全平台券池 -> 403/1002（与 create 同权限口径）。"""
    m = await _create_merchant(db_session, "券池越权店")
    cred = await _create_role3_admin(db_session, m.id)
    token = (await _login(db_client, cred))["token"]
    r = await db_client.get("/api/admin/coupon-pools", headers=_auth(token))
    assert r.status_code == 403
    assert r.json()["code"] == 1002


async def test_coupon_pool_create_validation(
    db_session: AsyncSession, db_client: AsyncClient, admin_authed: dict
):
    token = (await _login(db_client, admin_authed))["token"]
    cases = [
        {"name": "折扣缺rate", "type": 2, "scope": 4, "total_count": 5},  # 折扣券缺 discount_rate
        {"name": "折扣越界", "type": 2, "scope": 4, "discount_rate": 1.5, "total_count": 5},
        {"name": "满减零金额", "type": 1, "scope": 4, "amount": 0, "total_count": 5},
        {"name": "零张池", "type": 1, "scope": 4, "amount": 5, "total_count": 0},  # P2-4：0 拒绝
    ]
    for body in cases:
        r = await db_client.post("/api/admin/coupon-pools", json=body, headers=_auth(token))
        assert r.status_code == 422, body
        assert r.json()["code"] == 2001, body


async def test_grant_success_increments_and_generates_coupons(
    db_session: AsyncSession, db_client: AsyncClient, admin_authed: dict
):
    token = (await _login(db_client, admin_authed))["token"]
    user = User(openid="grant-user", nickname="领券人")
    db_session.add(user)
    await db_session.commit()
    r = await db_client.post(
        "/api/admin/coupon-pools",
        json={"name": "发放池", "type": 3, "scope": 1, "amount": 20, "total_count": 5},
        headers=_auth(token),
    )
    pool_id = r.json()["data"]["id"]

    r = await db_client.post(
        f"/api/admin/coupon-pools/{pool_id}/grant",
        json={"pool_id": pool_id, "user_id": user.id, "count": 2},
        headers=_auth(token),
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["granted_count"] == 2 and data["user_id"] == user.id
    assert len(data["coupons"]) == 2
    for c in data["coupons"]:
        assert c["code"].startswith("CP") and len(c["code"]) == 10
        assert c["status"] == 1 and c["amount"] == 20 and c["type"] == 3
    n = await db_session.scalar(
        select(func.count()).select_from(Coupon).where(Coupon.pool_id == pool_id)
    )
    assert n == 2


async def test_grant_over_capacity(
    db_session: AsyncSession, db_client: AsyncClient, admin_authed: dict
):
    token = (await _login(db_client, admin_authed))["token"]
    user = User(openid="over-user", nickname="超额人")
    db_session.add(user)
    await db_session.commit()
    r = await db_client.post(
        "/api/admin/coupon-pools",
        json={"name": "小池子", "type": 3, "scope": 1, "amount": 5, "total_count": 1},
        headers=_auth(token),
    )
    pool_id = r.json()["data"]["id"]

    r = await db_client.post(
        f"/api/admin/coupon-pools/{pool_id}/grant",
        json={"pool_id": pool_id, "user_id": user.id, "count": 2},
        headers=_auth(token),
    )
    assert r.status_code == 409
    assert r.json()["code"] == 4001
    # 未产生任何券与计数
    granted = await db_session.scalar(
        select(func.count()).select_from(Coupon).where(Coupon.pool_id == pool_id)
    )
    assert granted == 0


# ---- 订单监控 ----


async def test_orders_merchant_role_scope(
    db_session: AsyncSession, db_client: AsyncClient, admin_authed: dict
):
    m1 = await _create_merchant(db_session, "本家店")
    m2 = await _create_merchant(db_session, "别家店")
    user = User(openid="order-user")
    db_session.add(user)
    await db_session.flush()
    for m in (m1, m2):
        db_session.add(
            Order(
                order_no=f"NO-{m.id}",
                user_id=user.id,
                merchant_id=m.id,
                total_amount=30,
                pay_amount=30,
                status=2,
            )
        )
    await db_session.commit()
    cred = await _create_role3_admin(db_session, m1.id)
    shop_token = (await _login(db_client, cred))["token"]
    root_token = (await _login(db_client, admin_authed))["token"]

    # 商家角色：即使传 merchant_id=m2 也被强制过滤为本商家
    r = await db_client.get(
        "/api/admin/orders", params={"merchant_id": m2.id}, headers=_auth(shop_token)
    )
    assert r.status_code == 200
    items = r.json()["data"]["items"]
    assert len(items) == 1 and items[0]["merchant_id"] == m1.id

    # 超管：全量可见
    r = await db_client.get("/api/admin/orders", headers=_auth(root_token))
    assert r.status_code == 200
    assert r.json()["data"]["page"]["total"] == 2
