"""Phase 5 / F1：退款闭环 + 微信支付 APIv3 签名/验签/解密单测。

覆盖两类：
1. 退款（真实跑）：2→5 成功、重复退款幂等、未支付 2001、他人订单 1002、不存在 3001、
   退款后不可核销 5002；
2. 微信支付骨架（真实跑）：**测试内自造 RSA 密钥对**验证请求签名/回调验签，AES-256-GCM
   解密（NIST 向量）与篡改检测，无密钥降级标记。

不重复 tests/test_orders.py 已有断言（回调验签/幂等/超时/核销已在那里）。
"""

import base64
import math
import secrets

import pytest
from sqlalchemy import select

from app.core.security import create_access_token
from app.models import Merchant, MerchantSku, Order, SkuCatalog, User
from app.services import wechat_pay as w
from app.services.order_service import notify_sign

# ---------------------------------------------------------------------------
# 造数助手（独立于 test_orders，避免耦合）
# ---------------------------------------------------------------------------


async def _seed_merchant(db_session, name="退款测试店", category="轻食", status=1, audit_status=1):
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


async def _other_user(db_session, openid="refund-other"):
    user = User(openid=openid, gender=1)
    db_session.add(user)
    await db_session.flush()
    token = create_access_token(str(user.id), openid=user.openid)
    await db_session.commit()
    return {"user_id": user.id, "headers": {"Authorization": f"Bearer {token}"}}


async def _create_order(db_client, authed, merchant_id, items) -> dict:
    resp = await db_client.post(
        "/api/order",
        headers=authed["headers"],
        json={"merchant_id": merchant_id, "items": items},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


async def _get_order(db_session, order_id) -> Order:
    return (
        await db_session.execute(
            select(Order).where(Order.id == order_id).execution_options(populate_existing=True)
        )
    ).scalar_one()


async def _paid_order(db_client, db_session, authed, stock=-1):
    """造一个「2 已支付待核销」订单：下单 → notify。返回 (商家, 订单)。"""
    m = await _seed_merchant(db_session)
    sku = await _seed_sku(db_session, m.id, price=25.0, stock=stock)
    d = await _create_order(db_client, authed, m.id, [{"sku_id": sku.id, "qty": 1}])
    resp = await db_client.post(
        "/api/order/notify",
        json={"order_no": d["order_no"], "amount": d["pay_amount"],
              "sign": notify_sign(d["order_no"], d["pay_amount"])},
    )
    assert resp.status_code == 200, resp.text
    order = await _get_order(db_session, d["order_id"])
    assert order.status == 2
    return m, order


# ---------------------------------------------------------------------------
# 退款
# ---------------------------------------------------------------------------


async def test_refund_paid_order_transitions_2_to_5(db_client, db_session, authed):
    """已支付待核销订单退款成功：status 2→5，返回 refunded=True。"""
    _, order = await _paid_order(db_client, db_session, authed)

    resp = await db_client.post(
        f"/api/order/{order.id}/refund", headers=authed["headers"], json={"reason": "行程变更"}
    )
    body = resp.json()
    assert resp.status_code == 200 and body["code"] == 0
    data = body["data"]
    assert data["order_id"] == order.id and data["status"] == 5 and data["refunded"] is True
    assert (await _get_order(db_session, order.id)).status == 5


async def test_refund_is_idempotent(db_client, db_session, authed):
    """重复退款幂等：已 status=5 再次申请仍返回成功（refunded=true），不再重复流转。

    第二次不带 body，同时验证 requestBody 可选。
    """
    _, order = await _paid_order(db_client, db_session, authed)

    r1 = await db_client.post(f"/api/order/{order.id}/refund", headers=authed["headers"])
    assert r1.status_code == 200 and r1.json()["data"]["refunded"] is True

    r2 = await db_client.post(f"/api/order/{order.id}/refund", headers=authed["headers"])
    body2 = r2.json()
    assert r2.status_code == 200 and body2["code"] == 0
    assert body2["data"]["status"] == 5 and body2["data"]["refunded"] is True
    assert (await _get_order(db_session, order.id)).status == 5  # 仍为 5，未再流转


async def test_refund_unpaid_order_rejected_2001(db_client, db_session, authed):
    """未支付（status=1）订单退款 → 2001(422)。"""
    m = await _seed_merchant(db_session)
    sku = await _seed_sku(db_session, m.id)
    d = await _create_order(db_client, authed, m.id, [{"sku_id": sku.id, "qty": 1}])

    resp = await db_client.post(
        f"/api/order/{d['order_id']}/refund", headers=authed["headers"], json={}
    )
    assert resp.status_code == 422 and resp.json()["code"] == 2001
    assert (await _get_order(db_session, d["order_id"])).status == 1  # 未变


async def test_refund_other_user_order_rejected_1002(db_client, db_session, authed):
    """非本人订单退款 → 1002(403)，订单状态不变。"""
    _, order = await _paid_order(db_client, db_session, authed)
    other = await _other_user(db_session)

    resp = await db_client.post(
        f"/api/order/{order.id}/refund", headers=other["headers"], json={"reason": "蹭"}
    )
    assert resp.status_code == 403 and resp.json()["code"] == 1002
    assert (await _get_order(db_session, order.id)).status == 2


async def test_refund_missing_order_3001(db_client, db_session, authed):
    """不存在订单退款 → 3001(404)。"""
    resp = await db_client.post(
        "/api/order/999999/refund", headers=authed["headers"], json={}
    )
    assert resp.status_code == 404 and resp.json()["code"] == 3001


async def test_refunded_order_cannot_be_redeemed(db_client, db_session, authed):
    """已退款订单不得再核销 → 5003(409)（CD-10），状态停留 5。"""
    m, order = await _paid_order(db_client, db_session, authed)
    resp = await db_client.post(f"/api/order/{order.id}/refund", headers=authed["headers"])
    assert resp.status_code == 200

    r = await db_client.post(
        f"/api/order/{order.id}/redeem",
        headers=authed["headers"],
        json={"redeem_code": order.redeem_code, "merchant_id": m.id},
    )
    assert r.status_code == 409 and r.json()["code"] == 5003
    assert (await _get_order(db_session, order.id)).status == 5


# ---------------------------------------------------------------------------
# 微信支付骨架：测试内自造 RSA 密钥对（纯标准库生成 + DER/PEM 编码）
# ---------------------------------------------------------------------------

_SMALL_PRIMES = (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37)


def _is_probable_prime(n: int, rounds: int = 16) -> bool:
    if n < 2:
        return False
    for p in _SMALL_PRIMES:
        if n % p == 0:
            return n == p
    d, r = n - 1, 0
    while d % 2 == 0:
        d //= 2
        r += 1
    for _ in range(rounds):
        a = secrets.randbelow(n - 3) + 2
        x = pow(a, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(r - 1):
            x = x * x % n
            if x == n - 1:
                break
        else:
            return False
    return True


def _gen_prime(bits: int) -> int:
    while True:
        n = secrets.randbits(bits) | (1 << (bits - 1)) | 1
        if _is_probable_prime(n):
            return n


def _gen_rsa(bits: int = 1024) -> tuple[int, int, int, int, int]:
    """生成 RSA 密钥（测试用 1024 位即可覆盖签名路径，快且够）。"""
    e = 65537
    while True:
        p, q = _gen_prime(bits // 2), _gen_prime(bits // 2)
        if p == q:
            continue
        phi = (p - 1) * (q - 1)
        if math.gcd(e, phi) != 1:
            continue
        return p * q, e, pow(e, -1, phi), p, q


def _der_len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(b)]) + b


def _der_int(v: int) -> bytes:
    b = v.to_bytes((v.bit_length() + 7) // 8 or 1, "big")
    if b[0] & 0x80:
        b = b"\x00" + b
    return b"\x02" + _der_len(len(b)) + b


def _der_seq(*parts: bytes) -> bytes:
    body = b"".join(parts)
    return b"\x30" + _der_len(len(body)) + body


def _pem(tag: str, der: bytes) -> str:
    b = base64.b64encode(der).decode()
    body = "\n".join(b[i : i + 64] for i in range(0, len(b), 64))
    return f"-----BEGIN {tag}-----\n{body}\n-----END {tag}-----"


def _private_pem(n: int, e: int, d: int, p: int, q: int) -> str:
    der = _der_seq(
        _der_int(0), _der_int(n), _der_int(e), _der_int(d),
        _der_int(p), _der_int(q), _der_int(d % (p - 1)), _der_int(d % (q - 1)),
        _der_int(pow(q, -1, p)),
    )
    return _pem("RSA PRIVATE KEY", der)


def _public_pem(n: int, e: int) -> str:
    oid = bytes.fromhex("06092a864886f70d010101")  # 1.2.840.113549.1.1.1 (rsaEncryption)
    alg = _der_seq(oid, b"\x05\x00")  # OID + NULL
    rsa_pub = _der_seq(_der_int(n), _der_int(e))
    bit = b"\x03" + _der_len(len(rsa_pub) + 1) + b"\x00" + rsa_pub
    return _pem("PUBLIC KEY", _der_seq(alg, bit))


@pytest.fixture(scope="module")
def rsa_key() -> dict:
    n, e, d, p, q = _gen_rsa(1024)
    return {"priv": _private_pem(n, e, d, p, q), "pub": _public_pem(n, e)}


# ---------------------------------------------------------------------------
# 签名 / 验签
# ---------------------------------------------------------------------------


def test_request_authorization_sign_and_verify(rsa_key):
    """APIv3 请求签名：构造 WECHATPAY2-SHA256-RSA2048 头，可被同源公钥验签通过。"""
    cfg = w.WeChatPayConfig(
        appid="wxappid", mch_id="1900000001", serial_no="SERIAL123",
        api_v3_key="k" * 32, private_key_pem=rsa_key["priv"],
    )
    body = '{"out_trade_no":"DD1"}'
    auth = w.build_authorization(
        "POST", w.JSAPI_PATH, body, cfg=cfg, timestamp="1700000000", nonce="nonce-abc"
    )
    assert auth.startswith(w.AUTH_SCHEMA)
    assert f'mchid="{cfg.mch_id}"' in auth and f'serial_no="{cfg.serial_no}"' in auth
    assert w.verify_authorization(auth, "POST", w.JSAPI_PATH, body, rsa_key["pub"]) is True


def test_request_authorization_tampered_body_fails(rsa_key):
    """篡改报文体（金额）→ 验签失败。"""
    cfg = w.WeChatPayConfig(
        mch_id="1900000001", serial_no="S", api_v3_key="k" * 32, private_key_pem=rsa_key["priv"]
    )
    auth = w.build_authorization(
        "POST", w.JSAPI_PATH, '{"amount":{"total":100}}', cfg=cfg,
        timestamp="1700000000", nonce="n",
    )
    tampered = '{"amount":{"total":1}}'
    assert w.verify_authorization(auth, "POST", w.JSAPI_PATH, tampered, rsa_key["pub"]) is False


def test_notify_signature_ok(rsa_key):
    """回调验签：timestamp\\nnonce\\nbody\\n 的 RSA-SHA256 签名可验签通过。"""
    ts, nonce, body = "1700000000", "n1", '{"id":"evt-1"}'
    message = f"{ts}\n{nonce}\n{body}\n".encode()
    signature = w._rsa_sign(message, rsa_key["priv"])
    assert w.verify_notify_signature(ts, nonce, body, signature, rsa_key["pub"]) is True


def test_notify_signature_tampered_body_fails(rsa_key):
    """篡改回调报文（金额/内容）→ 验签失败。"""
    ts, nonce, body = "1700000000", "n1", '{"amount":{"total":100}}'
    signature = w._rsa_sign(f"{ts}\n{nonce}\n{body}\n".encode(), rsa_key["priv"])
    tampered = '{"amount":{"total":1}}'
    assert w.verify_notify_signature(ts, nonce, tampered, signature, rsa_key["pub"]) is False
    assert w.verify_notify_signature(ts, "n2", body, signature, rsa_key["pub"]) is False


# ---------------------------------------------------------------------------
# AES-256-GCM 解密（NIST AES-256-GCM Test Case 14 向量）
# ---------------------------------------------------------------------------


def test_decrypt_resource_nist_vector_ok():
    """NIST TC14：32 字节零密钥 + 12 字节零 IV，密文解密为 16 字节零明文。"""
    key = "\x00" * 32
    nonce = "\x00" * 12
    ct = base64.b64encode(
        bytes.fromhex("cea7403d4d606b6e074ec5d3baf39d18")
        + bytes.fromhex("d0d1c8a799996bf0265b98b5d48ab919")
    ).decode()
    assert w.decrypt_resource(ct, nonce, "", key) == "\x00" * 16


def test_decrypt_resource_tampered_tag_fails():
    """篡改 GCM tag 尾部字节 → 认证失败抛 WeChatPayError。"""
    key = "\x00" * 32
    nonce = "\x00" * 12
    raw = bytearray(
        bytes.fromhex("cea7403d4d606b6e074ec5d3baf39d18")
        + bytes.fromhex("d0d1c8a799996bf0265b98b5d48ab919")
    )
    raw[-1] ^= 0xFF
    ct = base64.b64encode(bytes(raw)).decode()
    with pytest.raises(w.WeChatPayError):
        w.decrypt_resource(ct, nonce, "", key)


# ---------------------------------------------------------------------------
# 无密钥降级 / 配置判定
# ---------------------------------------------------------------------------


def test_config_not_configured_by_default():
    """缺省（无商户号/密钥/证书）→ configured=False。"""
    from tests.conftest import make_settings

    assert w.load_config(make_settings()).configured is False
    # 仅填商户号+APIv3 密钥，仍缺 serial_no/私钥 → 未配置
    partial = w.load_config(make_settings(WECHAT_MCH_ID="1", WECHAT_PAY_KEY="k" * 32))
    assert partial.configured is False


async def test_prepare_payment_degraded_when_unconfigured():
    """未配置密钥 → prepare_payment 明确降级：degraded=True，参数不含 mock 标记。"""
    from types import SimpleNamespace

    from tests.conftest import make_settings

    order = SimpleNamespace(order_no="DD20250101000000AB", pay_amount=10.0)
    result = await w.prepare_payment(order, make_settings())
    assert result.degraded is True
    assert result.pay_params["degraded"] is True
    assert "mock" not in result.pay_params  # 非 mock 路径不得带 mock 标记
