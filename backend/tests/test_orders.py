"""订单域测试（BE6 Phase 3）：下单 → 支付 → 回调 → 核销 → 列表 全闭环。

一个行为一个测试、同类用 parametrize 合并；数据直接落 ORM（不依赖 merchant_service）。
sku_catalog 为库内种子目录（FD-001/002/003、SP-001/002），conftest 不清空。
"""

import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.security import create_access_token
from app.models import Coupon, Merchant, MerchantSku, Order, OrderItem, RedeemLog, SkuCatalog, User
from app.services.order_service import notify_sign, pay_sign

UTC = UTC
RE_ORDER_NO = re.compile(r"^DD\d{8}[0-9A-F]{8}$")  # DD + yyyyMMdd + 8 位随机大写 hex
RE_REDEEM_CODE = re.compile(r"^RD[A-Z0-9]{10}$")


# ---------------------------------------------------------------------------
# 造数助手
# ---------------------------------------------------------------------------


async def _seed_merchant(db_session, name="轻食一号店", category="轻食", status=1, audit_status=1):
    m = Merchant(name=name, category=category, status=status, audit_status=audit_status)
    db_session.add(m)
    await db_session.commit()
    return m


async def _seed_sku(db_session, merchant_id, code="FD-001", price=25.0, stock=-1, status=1):
    catalog_id = (
        await db_session.execute(select(SkuCatalog.id).where(SkuCatalog.code == code))
    ).scalar_one()
    sku = MerchantSku(
        merchant_id=merchant_id, catalog_id=catalog_id, price=price, stock=stock, status=status
    )
    db_session.add(sku)
    await db_session.commit()
    return sku


async def _seed_coupon(db_session, user_id, **kw):
    now = datetime.now(UTC)
    fields = dict(
        code=f"CP-{uuid.uuid4().hex[:16]}",
        type=1,
        scope=4,  # 通用，跳过 scope 匹配
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


async def _other_user(db_session, openid="order-other"):
    user = User(openid=openid, gender=1)
    db_session.add(user)
    await db_session.flush()
    token = create_access_token(str(user.id), openid=user.openid)
    await db_session.commit()
    return {"user_id": user.id, "headers": {"Authorization": f"Bearer {token}"}}


async def _create_order(db_client, authed, merchant_id, items, coupon_id=None) -> dict:
    body: dict = {"merchant_id": merchant_id, "items": items}
    if coupon_id is not None:
        body["coupon_id"] = coupon_id
    resp = await db_client.post("/api/order", headers=authed["headers"], json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


async def _get_order(db_session, order_id) -> Order:
    # app 会话已提交变更；populate_existing 强制用 DB 行刷新身份映射缓存对象
    return (
        await db_session.execute(
            select(Order).where(Order.id == order_id).execution_options(populate_existing=True)
        )
    ).scalar_one()


async def _get_coupon(db_session, coupon_id) -> Coupon:
    return (
        await db_session.execute(
            select(Coupon).where(Coupon.id == coupon_id).execution_options(populate_existing=True)
        )
    ).scalar_one()


async def _get_sku(db_session, sku_id) -> MerchantSku:
    return (
        await db_session.execute(
            select(MerchantSku)
            .where(MerchantSku.id == sku_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def _expire_order(db_session, order_id) -> None:
    order = await db_session.get(Order, order_id)
    order.expire_at = datetime.now(UTC) - timedelta(minutes=1)
    await db_session.commit()


def _notify_body(order_no: str, amount: float, sign: str | None = None) -> dict:
    return {"order_no": order_no, "amount": amount, "sign": sign or notify_sign(order_no, amount)}


# ---------------------------------------------------------------------------
# 下单
# ---------------------------------------------------------------------------


async def test_create_order_server_recalc(db_client, db_session, authed):
    """服务端按 SKU 价重算金额；前端伪造金额字段无效；快照/序列号/有效期正确。"""
    m = await _seed_merchant(db_session)
    sku = await _seed_sku(db_session, m.id, price=25.0)
    resp = await db_client.post(
        "/api/order",
        headers=authed["headers"],
        json={
            "merchant_id": m.id,
            "items": [{"sku_id": sku.id, "qty": 2}],
            "total_amount": 0.01,  # 前端伪造，应被忽略
            "pay_amount": 0.01,
            "discount_amount": 99.0,
        },
    )
    body = resp.json()
    assert resp.status_code == 200 and body["code"] == 0
    d = body["data"]
    assert (d["total_amount"], d["discount_amount"], d["pay_amount"]) == (50.0, 0.0, 50.0)
    assert RE_ORDER_NO.match(d["order_no"])
    left_min = (datetime.fromisoformat(d["expire_at"]) - datetime.now(UTC)).total_seconds() / 60
    assert 13 <= left_min <= 16  # ~15 分钟支付有效期

    order = await _get_order(db_session, d["order_id"])
    assert order.status == 1 and order.user_id == authed["user_id"] and order.merchant_id == m.id
    item = (
        await db_session.execute(select(OrderItem).where(OrderItem.order_id == order.id))
    ).scalar_one()
    assert item.sku_id == sku.id
    assert item.sku_name_snapshot == "经典鸡胸减脂餐"  # 目录名快照
    assert (item.unit_price, item.quantity, item.subtotal) == (25.0, 2, 50.0)


@pytest.mark.parametrize(
    "variant,code,http",
    [
        ("closed", 5001, 409),        # 商家停业
        ("unaudited", 3001, 404),     # 未过审视同不存在
        ("missing", 3001, 404),       # 商家不存在
        ("foreign_sku", 3001, 404),   # SKU 不属于该商家
        ("sku_off", 2001, 422),       # SKU 下架
        ("out_of_stock", 4001, 409),  # 库存不足（05 文档 §8.6 → 4001）
    ],
)
async def test_create_order_rejected(db_client, db_session, authed, variant, code, http):
    m = await _seed_merchant(db_session)
    sku = await _seed_sku(db_session, m.id, stock=1)
    payload = {"merchant_id": m.id, "items": [{"sku_id": sku.id, "qty": 1}]}
    if variant == "closed":
        m.status = 0
        await db_session.commit()
    elif variant == "unaudited":
        m.audit_status = 0
        await db_session.commit()
    elif variant == "missing":
        payload["merchant_id"] = 99999
    elif variant == "foreign_sku":
        m2 = await _seed_merchant(db_session, name="别家店")
        sku2 = await _seed_sku(db_session, m2.id, code="FD-002")
        payload["items"] = [{"sku_id": sku2.id, "qty": 1}]
    elif variant == "sku_off":
        sku.status = 0
        await db_session.commit()
    elif variant == "out_of_stock":
        payload["items"] = [{"sku_id": sku.id, "qty": 2}]  # stock=1

    resp = await db_client.post("/api/order", headers=authed["headers"], json=payload)
    body = resp.json()
    assert resp.status_code == http
    assert body["code"] == code


@pytest.mark.parametrize(
    "ctype,extra,expect_discount,expect_pay",
    [
        (1, {"amount": 5.0, "min_spend": 40.0}, 5.0, 48.0),  # 满减达标
        (2, {"discount_rate": 0.2}, 42.4, 10.6),  # 折扣：discount=53*(1-0.2)，2折付20%
        (3, {}, 28.0, 25.0),                                 # 免费：最高单价 SKU
        (4, {"amount": 2.0}, 2.0, 51.0),                     # 体验抵扣
    ],
)
async def test_create_order_coupon_types(
    db_client, db_session, authed, ctype, extra, expect_discount, expect_pay
):
    m = await _seed_merchant(db_session)
    s1 = await _seed_sku(db_session, m.id, "FD-001", price=25.0)
    s2 = await _seed_sku(db_session, m.id, "FD-003", price=28.0)
    cp = await _seed_coupon(db_session, authed["user_id"], type=ctype, **extra)
    d = await _create_order(
        db_client, authed, m.id, [{"sku_id": s1.id, "qty": 1}, {"sku_id": s2.id, "qty": 1}], cp.id
    )
    assert d["total_amount"] == 53.0
    assert d["discount_amount"] == expect_discount
    assert d["pay_amount"] == expect_pay
    coupon = await _get_coupon(db_session, cp.id)
    assert coupon.status == 2 and coupon.order_id == d["order_id"]  # 下单即绑券占位


@pytest.mark.parametrize(
    "variant", ["below_min", "foreign_owner", "used", "expired", "scope_mismatch"]
)
async def test_create_order_coupon_rejected(db_client, db_session, authed, variant):
    m = await _seed_merchant(db_session, category="轻食")
    sku = await _seed_sku(db_session, m.id, price=30.0)
    kw: dict = {"type": 1, "scope": 4, "amount": 5.0}
    owner_id = authed["user_id"]
    if variant == "below_min":
        kw["min_spend"] = 60.0  # total=30 不达标
    elif variant == "foreign_owner":
        other = await _other_user(db_session, "coupon-owner")
        owner_id = other["user_id"]
    elif variant == "used":
        kw["status"] = 2
    elif variant == "expired":
        kw["valid_to"] = datetime.now(UTC) - timedelta(days=1)
    elif variant == "scope_mismatch":
        kw["scope"] = 2  # 动 → 仅健身房；本店轻食
    cp = await _seed_coupon(db_session, owner_id, **kw)

    resp = await db_client.post(
        "/api/order",
        headers=authed["headers"],
        json={"merchant_id": m.id, "items": [{"sku_id": sku.id, "qty": 1}], "coupon_id": cp.id},
    )
    body = resp.json()
    assert resp.status_code == 409
    assert body["code"] == 5002
    coupon = await _get_coupon(db_session, cp.id)
    assert coupon.order_id is None  # 未被新订单绑定


# ---------------------------------------------------------------------------
# 支付（预下单）
# ---------------------------------------------------------------------------


async def test_pay_mock_mode_advances_order(db_app, db_client, db_session, authed):
    """P1-6 PAY_MOCK_MODE（显式开启）：pay 即支付成功——status=2、核销码、券 used_at、
    扣库存；pay_params 带 mock 标记且 paySign 可验算；他人订单 3001。"""
    from app.core.config import get_settings
    from tests.conftest import make_settings

    db_app.dependency_overrides[get_settings] = lambda: make_settings(PAY_MOCK_MODE=True)

    m = await _seed_merchant(db_session)
    sku = await _seed_sku(db_session, m.id, price=25.0, stock=5)
    cp = await _seed_coupon(db_session, authed["user_id"], amount=5.0)
    d = await _create_order(db_client, authed, m.id, [{"sku_id": sku.id, "qty": 2}], cp.id)

    resp = await db_client.post(f"/api/order/{d['order_id']}/pay", headers=authed["headers"])
    body = resp.json()
    assert resp.status_code == 200 and body["code"] == 0
    data = body["data"]
    assert data["status"] == 2
    p = data["pay_params"]
    assert p["mock"] is True
    assert p["package"].startswith("prepay_id=mock_")
    assert p["paySign"] == pay_sign(d["order_no"], p["timeStamp"], p["nonceStr"])

    order = await _get_order(db_session, d["order_id"])
    assert order.status == 2 and order.pay_at is not None
    assert RE_REDEEM_CODE.match(order.redeem_code)
    coupon = await _get_coupon(db_session, cp.id)
    assert coupon.used_at is not None and coupon.status == 2
    assert (await _get_sku(db_session, sku.id)).stock == 3  # 5 - 2

    other = await _other_user(db_session, "pay-other")
    resp = await db_client.post(f"/api/order/{d['order_id']}/pay", headers=other["headers"])
    assert resp.status_code == 404 and resp.json()["code"] == 3001  # 越权同 3001


async def test_pay_real_mode_keeps_pending(db_app, db_client, db_session, authed):
    """P1-6 PAY_MOCK_MODE=False：pay 只返回拉起参数不推进（等 notify），无 mock 标记。"""
    from app.core.config import get_settings
    from tests.conftest import make_settings

    db_app.dependency_overrides[get_settings] = lambda: make_settings(PAY_MOCK_MODE=False)
    m = await _seed_merchant(db_session)
    sku = await _seed_sku(db_session, m.id, price=25.0)
    d = await _create_order(db_client, authed, m.id, [{"sku_id": sku.id, "qty": 1}])

    resp = await db_client.post(f"/api/order/{d['order_id']}/pay", headers=authed["headers"])
    body = resp.json()
    assert resp.status_code == 200 and body["code"] == 0
    assert body["data"]["status"] == 1
    assert "mock" not in body["data"]["pay_params"]
    order = await _get_order(db_session, d["order_id"])
    assert order.status == 1  # 未推进，等 notify

    # notify 仍可正常推进（真实支付路径不变）
    r = await db_client.post("/api/order/notify", json=_notify_body(d["order_no"], d["pay_amount"]))
    assert r.status_code == 200
    assert (await _get_order(db_session, d["order_id"])).status == 2


async def test_pay_expired_5003_cancels_and_releases_coupon(db_client, db_session, authed):
    m = await _seed_merchant(db_session)
    sku = await _seed_sku(db_session, m.id)
    cp = await _seed_coupon(db_session, authed["user_id"], amount=5.0)
    d = await _create_order(db_client, authed, m.id, [{"sku_id": sku.id, "qty": 1}], cp.id)
    await _expire_order(db_session, d["order_id"])

    resp = await db_client.post(f"/api/order/{d['order_id']}/pay", headers=authed["headers"])
    body = resp.json()
    assert resp.status_code == 409 and body["code"] == 5003

    order = await _get_order(db_session, d["order_id"])
    assert order.status == 4  # 已取消
    coupon = await _get_coupon(db_session, cp.id)
    assert coupon.status == 1 and coupon.order_id is None  # 券释放


# ---------------------------------------------------------------------------
# 回调
# ---------------------------------------------------------------------------


async def test_notify_success_marks_paid(db_client, db_session, authed):
    """正常回调：置已支付 + 核销码 + 券 used_at + 扣库存。"""
    m = await _seed_merchant(db_session)
    sku = await _seed_sku(db_session, m.id, price=25.0, stock=5)
    cp = await _seed_coupon(db_session, authed["user_id"], amount=5.0)
    d = await _create_order(db_client, authed, m.id, [{"sku_id": sku.id, "qty": 2}], cp.id)

    resp = await db_client.post(
        "/api/order/notify", json=_notify_body(d["order_no"], d["pay_amount"])
    )
    body = resp.json()
    assert resp.status_code == 200 and body["code"] == 0
    assert body["data"] == {"result": "ok"}

    order = await _get_order(db_session, d["order_id"])
    assert order.status == 2 and order.pay_at is not None
    assert RE_REDEEM_CODE.match(order.redeem_code)
    coupon = await _get_coupon(db_session, cp.id)
    assert coupon.used_at is not None and coupon.status == 2
    sku_row = await _get_sku(db_session, sku.id)
    assert sku_row.stock == 3  # 5 - 2（按数量扣，-1 不限量除外）


@pytest.mark.parametrize(
    "variant,code,http",
    [
        ("bad_sign", 2001, 422),        # 签名错误
        ("tampered_amount", 2001, 422),  # 改金额留原签名 → 验签失败
        ("amount_mismatch", 2001, 422),  # 签名合法但金额≠应付（防篡改兜底）
        ("unknown_order", 3001, 404),    # 订单不存在
        ("missing_fields", 2001, 422),   # 缺参
    ],
)
async def test_notify_rejected(db_client, db_session, authed, variant, code, http):
    m = await _seed_merchant(db_session)
    sku = await _seed_sku(db_session, m.id, price=25.0)
    d = await _create_order(db_client, authed, m.id, [{"sku_id": sku.id, "qty": 1}])
    if variant == "bad_sign":
        body = {"order_no": d["order_no"], "amount": d["pay_amount"], "sign": "0" * 64}
    elif variant == "tampered_amount":
        body = {
            "order_no": d["order_no"],
            "amount": 0.01,
            "sign": notify_sign(d["order_no"], d["pay_amount"]),  # 原金额签名
        }
    elif variant == "amount_mismatch":
        body = _notify_body(d["order_no"], 999.0)  # 对 999 的合法签名
    elif variant == "unknown_order":
        body = _notify_body("DD20990101000001", 25.0)
    else:
        body = {"order_no": d["order_no"]}

    resp = await db_client.post("/api/order/notify", json=body)
    result = resp.json()
    assert resp.status_code == http
    assert result["code"] == code
    assert (await _get_order(db_session, d["order_id"])).status == 1  # 状态未推进


async def test_notify_idempotent_and_timeout(db_client, db_session, authed):
    """重复回调幂等（库存只扣一次）；超时单回调 → 5003 + 取消 + 券释放。"""
    m = await _seed_merchant(db_session)
    sku = await _seed_sku(db_session, m.id, price=25.0, stock=3)
    d = await _create_order(db_client, authed, m.id, [{"sku_id": sku.id, "qty": 1}])
    body = _notify_body(d["order_no"], d["pay_amount"])
    assert (await db_client.post("/api/order/notify", json=body)).json()["code"] == 0
    assert (await db_client.post("/api/order/notify", json=body)).json()["code"] == 0
    assert (await _get_order(db_session, d["order_id"])).status == 2
    assert (await _get_sku(db_session, sku.id)).stock == 2  # 只扣一次

    # 超时单
    cp = await _seed_coupon(db_session, authed["user_id"], amount=1.0)
    d2 = await _create_order(db_client, authed, m.id, [{"sku_id": sku.id, "qty": 1}], cp.id)
    await _expire_order(db_session, d2["order_id"])
    resp = await db_client.post(
        "/api/order/notify", json=_notify_body(d2["order_no"], d2["pay_amount"])
    )
    assert resp.status_code == 409 and resp.json()["code"] == 5003
    assert (await _get_order(db_session, d2["order_id"])).status == 4
    coupon = await _get_coupon(db_session, cp.id)
    assert coupon.status == 1 and coupon.order_id is None

    # P2-3：已取消订单收到迟到回调 → 5003（不再幂等 ok）
    r2 = await db_client.post(
        "/api/order/notify", json=_notify_body(d2["order_no"], d2["pay_amount"])
    )
    assert r2.status_code == 409 and r2.json()["code"] == 5003


async def test_notify_stock_shortage_blocks_oversell(db_client, db_session, authed):
    """P0-2 库存 1：A 单支付成功扣到 0；B 单无法再支付成功（下单 4001；
    即使下单校验被绕过——先下单后支付——notify 也 409/4001，订单停留待支付，stock 不会变 -1）。"""
    m = await _seed_merchant(db_session)
    sku = await _seed_sku(db_session, m.id, price=25.0, stock=1)
    other = await _other_user(db_session, "stock-other")
    # 两单都在 stock=1 时创建（模拟绕过下单余量校验的场景）
    d1 = await _create_order(db_client, authed, m.id, [{"sku_id": sku.id, "qty": 1}])
    d2 = await _create_order(db_client, other, m.id, [{"sku_id": sku.id, "qty": 1}])

    r1 = await db_client.post(
        "/api/order/notify", json=_notify_body(d1["order_no"], d1["pay_amount"])
    )
    assert r1.status_code == 200
    assert (await _get_sku(db_session, sku.id)).stock == 0

    # 第二单直接 notify：库存不足 → 409/4001，整个事务回滚
    r2 = await db_client.post(
        "/api/order/notify", json=_notify_body(d2["order_no"], d2["pay_amount"])
    )
    assert r2.status_code == 409 and r2.json()["code"] == 4001
    order2 = await _get_order(db_session, d2["order_id"])
    assert order2.status == 1  # 未推进（status=2/pay_at/redeem_code 全部回滚）
    assert order2.redeem_code is None
    assert (await _get_sku(db_session, sku.id)).stock == 0  # 不会变 -1

    # 恢复库存前，下单余量校验同样挡住
    resp = await db_client.post(
        "/api/order",
        headers=other["headers"],
        json={"merchant_id": m.id, "items": [{"sku_id": sku.id, "qty": 1}]},
    )
    assert resp.status_code == 409 and resp.json()["code"] == 4001


# ---------------------------------------------------------------------------
# 核销
# ---------------------------------------------------------------------------


async def _paid_order(db_client, db_session, authed, merchant, stock=-1):
    sku = await _seed_sku(db_session, merchant.id, price=25.0, stock=stock)
    d = await _create_order(db_client, authed, merchant.id, [{"sku_id": sku.id, "qty": 1}])
    resp = await db_client.post(
        "/api/order/notify", json=_notify_body(d["order_no"], d["pay_amount"])
    )
    assert resp.status_code == 200, resp.text
    order = await _get_order(db_session, d["order_id"])
    return order


async def test_redeem_success_then_duplicate_5004(db_client, db_session, authed):
    m = await _seed_merchant(db_session)
    order = await _paid_order(db_client, db_session, authed, m)
    payload = {"redeem_code": order.redeem_code, "merchant_id": m.id}

    r1 = await db_client.post(
        f"/api/order/{order.id}/redeem", headers=authed["headers"], json=payload
    )
    assert r1.status_code == 200 and r1.json()["data"]["status"] == "redeemed"
    assert (await _get_order(db_session, order.id)).status == 3  # 已完成
    logs = (
        (await db_session.execute(select(RedeemLog).where(RedeemLog.order_id == order.id)))
        .scalars()
        .all()
    )
    assert len(logs) == 1 and logs[0].result == 1 and logs[0].merchant_id == m.id

    r2 = await db_client.post(
        f"/api/order/{order.id}/redeem", headers=authed["headers"], json=payload
    )
    assert r2.status_code == 409 and r2.json()["code"] == 5004  # 已核销
    logs = (
        (await db_session.execute(select(RedeemLog).where(RedeemLog.order_id == order.id)))
        .scalars()
        .all()
    )
    assert len(logs) == 2 and logs[1].result == 2 and logs[1].fail_reason  # 失败留痕


async def test_redeem_wrong_merchant_rejected(db_client, db_session, authed):
    m = await _seed_merchant(db_session)
    order = await _paid_order(db_client, db_session, authed, m)
    m2 = await _seed_merchant(db_session, name="另一家店")

    resp = await db_client.post(
        f"/api/order/{order.id}/redeem",
        headers=authed["headers"],
        json={"redeem_code": order.redeem_code, "merchant_id": m2.id},
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == 5002  # 【假设】他人商家核销 → 5002(409)
    assert (await _get_order(db_session, order.id)).status == 2  # 未被核销
    logs = (
        (await db_session.execute(select(RedeemLog).where(RedeemLog.order_id == order.id)))
        .scalars()
        .all()
    )
    assert len(logs) == 1 and logs[0].result == 2


async def test_redeem_owner_mismatch_rejected(db_client, db_session, authed):
    """P1-3 商家已绑定 owner 且非本人 → 核销 1002/403（CD-10：无权限）。"""
    other = await _other_user(db_session, "owner-other")
    m = Merchant(
        name="有主店", category="轻食", audit_status=1, owner_user_id=other["user_id"]
    )
    db_session.add(m)
    await db_session.commit()
    order = await _paid_order(db_client, db_session, authed, m)

    resp = await db_client.post(
        f"/api/order/{order.id}/redeem",
        headers=authed["headers"],
        json={"redeem_code": order.redeem_code, "merchant_id": m.id},
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == 1002
    assert (await _get_order(db_session, order.id)).status == 2


async def test_redeem_owner_self_allowed(db_client, db_session, authed):
    """P1-3 owner 为本人 → 核销成功（owner=NULL 放行路径已由既有用例覆盖）。"""
    m = Merchant(
        name="本人店", category="轻食", audit_status=1, owner_user_id=authed["user_id"]
    )
    db_session.add(m)
    await db_session.commit()
    order = await _paid_order(db_client, db_session, authed, m)

    resp = await db_client.post(
        f"/api/order/{order.id}/redeem",
        headers=authed["headers"],
        json={"redeem_code": order.redeem_code, "merchant_id": m.id},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "redeemed"
    assert (await _get_order(db_session, order.id)).status == 3


@pytest.mark.parametrize("status,reason", [(4, "订单已取消"), (5, "订单已退款")])
async def test_redeem_cancelled_or_refunded_5003(
    db_client, db_session, authed, status, reason
):
    """CD-10：已取消/已退款订单核销 → 5003/409（message 写明原因），失败留痕。"""
    m = await _seed_merchant(db_session)
    order = await _paid_order(db_client, db_session, authed, m)
    order.status = status
    await db_session.commit()

    resp = await db_client.post(
        f"/api/order/{order.id}/redeem",
        headers=authed["headers"],
        json={"redeem_code": order.redeem_code, "merchant_id": m.id},
    )
    assert resp.status_code == 409
    body = resp.json()
    assert body["code"] == 5003
    assert reason in body["message"]
    assert (await _get_order(db_session, order.id)).status == status  # 未被核销
    log = (
        (await db_session.execute(select(RedeemLog).where(RedeemLog.order_id == order.id)))
        .scalars()
        .one()
    )
    assert log.result == 2 and reason in log.fail_reason


# ---------------------------------------------------------------------------
# 列表 + 惰性超时
# ---------------------------------------------------------------------------


async def test_order_list_lazy_timeout_and_filter(db_client, db_session, authed):
    """查询前惰性取消超时单；merchant_name join；status 过滤。"""
    m = await _seed_merchant(db_session)
    sku = await _seed_sku(db_session, m.id)
    d1 = await _create_order(db_client, authed, m.id, [{"sku_id": sku.id, "qty": 1}])
    d2 = await _create_order(db_client, authed, m.id, [{"sku_id": sku.id, "qty": 1}])
    await _expire_order(db_session, d2["order_id"])  # 只改 expire_at，status 仍 1

    resp = await db_client.get("/api/order/list", headers=authed["headers"])
    body = resp.json()
    assert resp.status_code == 200 and body["code"] == 0
    data = body["data"]
    assert data["page"]["total"] == 2
    by_no = {i["order_no"]: i for i in data["items"]}
    assert by_no[d1["order_no"]]["status"] == 1
    assert by_no[d2["order_no"]]["status"] == 4  # 惰性取消
    assert by_no[d1["order_no"]]["merchant_name"] == "轻食一号店"

    resp = await db_client.get("/api/order/list?status=1", headers=authed["headers"])
    data = resp.json()["data"]
    assert data["page"]["total"] == 1 and data["items"][0]["order_no"] == d1["order_no"]

    # 别人的订单不可见（行级隔离）
    other = await _other_user(db_session, "list-other")
    resp = await db_client.get("/api/order/list", headers=other["headers"])
    assert resp.json()["data"]["page"]["total"] == 0
