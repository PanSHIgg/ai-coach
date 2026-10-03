"""BE9 管理 API 集成测试：登录/审核/选品定价/券池/发放/订单监控。

均走真实 PostgreSQL（db_client + db_session，DATABASE_URL 指向隔离库）；
token 一律经 /api/admin/login 获取（与 C 端 JWT 体系解耦）。
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models import AdminUser, Coupon, Merchant, MerchantSku, Order, SkuCatalog, User

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
    sku_body = {"code": "FD-900", "name": "x", "base_price": 1, "min_price": 1, "max_price": 1}
    cases = [
        ("GET", "/api/admin/merchants", None),
        ("POST", "/api/admin/merchants/1/audit", {"audit_status": 1}),
        ("POST", "/api/admin/merchant-skus", {"merchant_id": 1, "catalog_id": 1, "price": 25}),
        ("POST", "/api/admin/merchant-skus/1/status", {"status": 0}),
        ("GET", "/api/admin/coupon-pools", None),
        ("POST", "/api/admin/coupon-pools/1/grant", {"pool_id": 1, "user_id": 1}),
        ("GET", "/api/admin/orders", None),
        ("GET", "/api/admin/dashboard", None),
        ("POST", "/api/admin/sku-catalog", sku_body),
        ("PUT", "/api/admin/sku-catalog/1", sku_body),
        ("GET", "/api/admin/accounts", None),
        ("POST", "/api/admin/accounts", {"username": "x", "password": "Whatever@123", "role": 3}),
        ("PUT", "/api/admin/accounts/1/password", {"new_password": "Whatever@123"}),
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


@pytest.fixture
async def created_catalog_codes(db_session: AsyncSession):
    """登记本用例新建的标准目录编码，用例结束后删除。

    sku_catalog 是种子参照表（conftest 不 TRUNCATE），不清理会污染
    test_admin_sku_catalog 的「恰好 5 行」断言（重复运行时尤为明显）。
    """
    codes: list[str] = []
    yield codes
    if codes:
        await db_session.execute(delete(SkuCatalog).where(SkuCatalog.code.in_(codes)))
        await db_session.commit()


async def test_create_and_update_sku_catalog(
    db_client: AsyncClient, admin_authed: dict, created_catalog_codes: list[str]
):
    """POST 新建（区间合法）+ PUT 编辑；不存在 id -> 3001/404。"""
    token = (await _login(db_client, admin_authed))["token"]
    created_catalog_codes.append("FD-901")

    r = await db_client.post(
        "/api/admin/sku-catalog",
        json={
            "code": "FD-901",
            "name": "测试轻食碗",
            "category": "标准减脂餐",
            "calories_low": 300,
            "calories_high": 480,
            "base_price": 30.0,
            "min_price": 25.0,
            "max_price": 40.0,
            "unit": "份",
        },
        headers=_auth(token),
    )
    assert r.status_code == 200 and r.json()["code"] == 0
    item = r.json()["data"]
    assert item["code"] == "FD-901" and item["name"] == "测试轻食碗"
    assert item["min_price"] == 25.0 and item["base_price"] == 30.0 and item["max_price"] == 40.0

    cid = item["id"]
    r = await db_client.put(
        f"/api/admin/sku-catalog/{cid}",
        json={
            "code": "FD-901",
            "name": "测试轻食碗(改)",
            "category": "标准减脂餐",
            "base_price": 28.0,
            "min_price": 22.0,
            "max_price": 38.0,
            "unit": "盒",
        },
        headers=_auth(token),
    )
    assert r.status_code == 200 and r.json()["code"] == 0
    upd = r.json()["data"]
    assert upd["id"] == cid and upd["name"] == "测试轻食碗(改)" and upd["unit"] == "盒"

    # 编辑不存在的目录项 -> 3001/404
    r = await db_client.put(
        "/api/admin/sku-catalog/99999",
        json={"code": "FD-999", "name": "不存在", "base_price": 1, "min_price": 1, "max_price": 1},
        headers=_auth(token),
    )
    assert r.status_code == 404 and r.json()["code"] == 3001


async def test_create_sku_catalog_validation(db_client: AsyncClient, admin_authed: dict):
    """区间越界 / 缺必填 -> 422/2001；编码重名（引用种子 FD-001）-> 2001/422。"""
    token = (await _login(db_client, admin_authed))["token"]
    for body in (
        {"code": "FD-902", "name": "越界A", "base_price": 20, "min_price": 30, "max_price": 40},
        {"code": "FD-903", "name": "越界B", "base_price": 50, "min_price": 10, "max_price": 40},
        {"name": "缺编码", "base_price": 10, "min_price": 10, "max_price": 10},
        {"code": "FD-904", "name": "", "base_price": 10, "min_price": 10, "max_price": 10},
    ):
        r = await db_client.post("/api/admin/sku-catalog", json=body, headers=_auth(token))
        assert r.status_code == 422, body
        assert r.json()["code"] == 2001, body

    r = await db_client.post(
        "/api/admin/sku-catalog",
        json={"code": "FD-001", "name": "重名", "base_price": 10, "min_price": 10, "max_price": 10},
        headers=_auth(token),
    )
    assert r.status_code == 422 and r.json()["code"] == 2001


async def test_sku_catalog_write_denied_for_merchant_role(
    db_session: AsyncSession, db_client: AsyncClient
):
    """role=3 商家账号维护标准目录 -> 403/1002（平台级操作）。"""
    m = await _create_merchant(db_session, "目录越权店")
    cred = await _create_role3_admin(db_session, m.id)
    token = (await _login(db_client, cred))["token"]
    body = {"code": "FD-905", "name": "越权", "base_price": 10, "min_price": 10, "max_price": 10}
    for method, url in (("post", "/api/admin/sku-catalog"), ("put", "/api/admin/sku-catalog/1")):
        r = await getattr(db_client, method)(url, json=body, headers=_auth(token))
        assert r.status_code == 403, url
        assert r.json()["code"] == 1002, url


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
        assert r.status_code == 400, price
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


# ---- 账号管理（超管/运营开通后台账号）----

_STRONG_PW = "Ops@2026#StrongPW"  # 过统一弱口令策略（≥12 位、非黑名单）


async def test_accounts_list_empty_then_created(
    db_client: AsyncClient, admin_authed: dict, db_session: AsyncSession
):
    """role=1：列表初始只含自身；创建运营/商家后回填。"""
    token = _auth((await _login(db_client, admin_authed))["token"])

    r = await db_client.get("/api/admin/accounts", headers=token)
    assert r.status_code == 200 and r.json()["code"] == 0
    assert r.json()["data"]["page"]["total"] == 1  # 只有超管自己
    assert r.json()["data"]["items"][0]["username"] == admin_authed["username"]

    m = await _create_merchant(db_session, "绿野轻食")
    r = await db_client.post(
        "/api/admin/accounts",
        headers=token,
        json={"username": "ops-oncall", "password": _STRONG_PW, "role": 2},
    )
    assert r.status_code == 200 and r.json()["code"] == 0
    assert r.json()["data"]["role"] == 2 and r.json()["data"]["merchant_id"] is None

    r = await db_client.post(
        "/api/admin/accounts",
        headers=token,
        json={"username": "shop-front", "password": _STRONG_PW, "role": 3, "merchant_id": m.id},
    )
    assert r.status_code == 200
    assert r.json()["data"]["merchant_id"] == m.id

    r = await db_client.get("/api/admin/accounts", headers=token)
    assert r.json()["data"]["page"]["total"] == 3
    usernames = {it["username"] for it in r.json()["data"]["items"]}
    assert {"ops-oncall", "shop-front"} <= usernames


async def test_accounts_create_permission_matrix(
    db_client: AsyncClient, admin_authed: dict, db_session: AsyncSession
):
    """运营可建商家账号；建运营/超管被 1002；role=4 一律 2001；商家看列表 1002。"""
    m = await _create_merchant(db_session, "矩阵商家")
    ops_cred = {"username": f"ops-{m.id}", "password": _STRONG_PW}
    r = await db_client.post(
        "/api/admin/accounts",
        headers=_auth((await _login(db_client, admin_authed))["token"]),
        json={"username": ops_cred["username"], "password": _STRONG_PW, "role": 2},
    )
    assert r.status_code == 200
    ops_token = (await _login(db_client, ops_cred))["token"]
    ops_headers = _auth(ops_token)

    # 运营建商家 ✓
    r = await db_client.post(
        "/api/admin/accounts",
        headers=ops_headers,
        json={
            "username": f"shop-front-{m.id}",
            "password": _STRONG_PW,
            "role": 3,
            "merchant_id": m.id,
        },
    )
    assert r.status_code == 200 and r.json()["data"]["role"] == 3

    # 运营建运营 / 建超管 ✗ 1002
    for role in (2, 1):
        r = await db_client.post(
            "/api/admin/accounts",
            headers=ops_headers,
            json={"username": f"probe-{role}", "password": _STRONG_PW, "role": role},
        )
        assert r.status_code == 403 and r.json()["code"] == 1002, r.text

    # role=4 教练不经此接口（超管/运营都一样）✗ 2001/422
    root_headers = _auth((await _login(db_client, admin_authed))["token"])
    for headers in (root_headers, ops_headers):
        r = await db_client.post(
            "/api/admin/accounts",
            headers=headers,
            json={"username": f"coach-{m.id}", "password": _STRONG_PW, "role": 4},
        )
        assert r.status_code == 422 and r.json()["code"] == 2001

    # 商家角色访问账号列表 ✗ 1002
    shop_cred = await _create_role3_admin(db_session, m.id)
    shop_token = (await _login(db_client, shop_cred))["token"]
    r = await db_client.get("/api/admin/accounts", headers=_auth(shop_token))
    assert r.status_code == 403 and r.json()["code"] == 1002


async def test_accounts_create_validation_errors(
    db_client: AsyncClient, admin_authed: dict, db_session: AsyncSession
):
    """重名 2001 / 商家不存在 2001 / role=3 缺 merchant_id 2001 / 非商家绑 merchant_id 2001 / 弱口令 2001。"""
    token = _auth((await _login(db_client, admin_authed))["token"])

    r = await db_client.post(
        "/api/admin/accounts",
        headers=token,
        json={"username": admin_authed["username"], "password": _STRONG_PW, "role": 2},
    )
    assert r.status_code == 422 and r.json()["code"] == 2001  # 与超管重名

    r = await db_client.post(
        "/api/admin/accounts",
        headers=token,
        json={"username": "shop-x", "password": _STRONG_PW, "role": 3, "merchant_id": 999999},
    )
    assert r.status_code == 422 and r.json()["code"] == 2001  # 商家不存在

    r = await db_client.post(
        "/api/admin/accounts",
        headers=token,
        json={"username": "shop-nobind", "password": _STRONG_PW, "role": 3},
    )
    assert r.status_code == 422 and r.json()["code"] == 2001  # role=3 缺 merchant_id

    r = await db_client.post(
        "/api/admin/accounts",
        headers=token,
        json={"username": "ops-bind", "password": _STRONG_PW, "role": 2, "merchant_id": 1},
    )
    assert r.status_code == 422 and r.json()["code"] == 2001  # 非商家绑定 merchant_id

    # 弱口令（公开种子口令在黑名单）→ 2001
    r = await db_client.post(
        "/api/admin/accounts",
        headers=token,
        json={"username": "weak-pw", "password": "Admin@123456", "role": 2},
    )
    assert r.status_code == 422 and r.json()["code"] == 2001


async def test_accounts_password_reset(
    db_client: AsyncClient, admin_authed: dict, db_session: AsyncSession
):
    """超管重置任意账号；旧密码失效、新密码可登录；账号不存在 404/3001。"""
    m = await _create_merchant(db_session, "重置商家")
    shop_cred = await _create_role3_admin(db_session, m.id)
    root_token = _auth((await _login(db_client, admin_authed))["token"])

    r = await db_client.get("/api/admin/accounts", headers=root_token)
    shop = next(
        it for it in r.json()["data"]["items"] if it["username"] == shop_cred["username"]
    )

    new_pw = "Reset@2026#Strong"
    r = await db_client.put(
        f"/api/admin/accounts/{shop['id']}/password",
        headers=root_token,
        json={"new_password": new_pw},
    )
    assert r.status_code == 200 and r.json()["code"] == 0

    # 旧密码失效
    r = await db_client.post("/api/admin/login", json=shop_cred)
    assert r.status_code == 401
    # 新密码可登录
    r = await db_client.post(
        "/api/admin/login", json={"username": shop_cred["username"], "password": new_pw}
    )
    assert r.status_code == 200 and r.json()["code"] == 0

    # 账号不存在 → 404/3001
    r = await db_client.put(
        "/api/admin/accounts/999999/password", headers=root_token, json={"new_password": new_pw}
    )
    assert r.status_code == 404 and r.json()["code"] == 3001


async def test_accounts_reset_permission_matrix(
    db_client: AsyncClient, admin_authed: dict, db_session: AsyncSession
):
    """运营可重置商家账号密码，但不可重置运营账号密码。"""
    m = await _create_merchant(db_session, "重置矩阵")
    shop_cred = await _create_role3_admin(db_session, m.id)

    ops_cred = {"username": f"ops-{m.id}", "password": _STRONG_PW}
    root_token = _auth((await _login(db_client, admin_authed))["token"])
    r = await db_client.post(
        "/api/admin/accounts",
        headers=root_token,
        json={"username": ops_cred["username"], "password": _STRONG_PW, "role": 2},
    )
    assert r.status_code == 200
    ops_id = r.json()["data"]["id"]
    ops_token = (await _login(db_client, ops_cred))["token"]

    # 运营重置商家账号 ✓
    r = await db_client.get("/api/admin/accounts", headers=_auth(ops_token))
    shop = next(
        it for it in r.json()["data"]["items"] if it["username"] == shop_cred["username"]
    )
    r = await db_client.put(
        f"/api/admin/accounts/{shop['id']}/password",
        headers=_auth(ops_token),
        json={"new_password": "NewShop@2026#1"},
    )
    assert r.status_code == 200

    # 运营重置运营账号（自己）✗ 1002
    r = await db_client.put(
        f"/api/admin/accounts/{ops_id}/password",
        headers=_auth(ops_token),
        json={"new_password": "NewOps@2026#1"},
    )
    assert r.status_code == 403 and r.json()["code"] == 1002


async def test_login_rejects_role4(
    db_client: AsyncClient, admin_authed: dict, db_session: AsyncSession
):
    """role=4 教练账号登录 admin web → 403/1002（教练端独立；修复前端无限重定向缺陷）。"""
    m = await _create_merchant(db_session, "教练测试")
    cred = {"username": f"coach-{m.id}", "password": "Coach@123456"}
    db_session.add(
        AdminUser(
            username=cred["username"],
            password_hash=hash_password(cred["password"]),
            role=4,
            merchant_id=None,
        )
    )
    await db_session.commit()

    r = await db_client.post("/api/admin/login", json=cred)
    assert r.status_code == 403
    assert r.json()["code"] == 1002
