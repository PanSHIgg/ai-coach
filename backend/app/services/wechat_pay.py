"""微信支付 APIv3 接入骨架（F1 硬化）。

设计约束（沙箱 / 生产共用）：
- **纯标准库实现**，不引入任何未安装的三方 SDK（沙箱无 cryptography/wechatpay 包）。
  RSA-SHA256（PKCS#1 v1.5）与 AES-256-GCM 均为自实现，仅覆盖微信支付 APIv3 所需子集。
- 商户私钥 / 平台证书 / APIv3 密钥从配置读取：优先 Settings 字段（若存在），
  其次同名环境变量（支持直接放 PEM 内容或用 *_PATH 指文件）。**不修改 core/config.py**。
- 未配置密钥时**明确降级**：`prepare_payment` 返回 `degraded=True` 的占位参数，
  由调用方（order_service.pay_order）走既有本地路径，绝不静默伪造真实签名。
- 本模块只做「可真实接入」的骨架：真实统一下单的 HTTP 调用已写好，但沙箱内不执行。

【假设】字段命名沿用统一约定，未在 core/config.py 落地的配置项（如 serial_no / 证书路径）
以环境变量形式读取，详见 docs/微信支付联调手册.md。
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from dataclasses import dataclass
from typing import Any

from app.core.config import Settings, get_settings

AUTH_SCHEMA = "WECHATPAY2-SHA256-RSA2048"
JSAPI_URL = "https://api.mch.weixin.qq.com/v3/pay/transactions/jsapi"
JSAPI_PATH = "/v3/pay/transactions/jsapi"


class WeChatPayError(Exception):
    """微信支付交互/解析失败（骨架层统一异常）。"""


# ---------------------------------------------------------------------------
# 配置读取（宽松：Settings 字段 → 环境变量 → *_PATH 文件）
# ---------------------------------------------------------------------------


@dataclass
class WeChatPayConfig:
    """微信支付运行期配置快照。"""

    appid: str = ""
    mch_id: str = ""
    serial_no: str = ""
    api_v3_key: str = ""
    private_key_pem: str = ""
    platform_public_key_pem: str = ""
    notify_url: str = ""

    @property
    def configured(self) -> bool:
        """真实联调所需最小集合：商户号 + 证书序列号 + 私钥 + APIv3 密钥。"""
        return bool(
            self.mch_id and self.serial_no and self.private_key_pem and self.api_v3_key
        )


def _resolve_pem(inline_name: str, path_name: str, settings: Settings) -> str:
    """读 PEM：环境变量/Settings 直放内容，或由 *_PATH 指向文件。"""
    inline = os.environ.get(inline_name) or getattr(settings, inline_name, "") or ""
    inline = str(inline).strip()
    if inline.startswith("-----BEGIN"):
        return inline
    path = os.environ.get(path_name) or getattr(settings, path_name, "") or ""
    path = str(path).strip()
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    return ""


def load_config(settings: Settings | None = None) -> WeChatPayConfig:
    """加载配置：Settings 字段优先，其次同名环境变量（不改 core/config.py）。"""
    s = settings or get_settings()

    def g(attr: str, env: str) -> str:
        return (getattr(s, attr, "") or os.environ.get(env, "") or "").strip()

    return WeChatPayConfig(
        appid=g("WECHAT_APPID", "WECHAT_APPID"),
        mch_id=g("WECHAT_MCH_ID", "WECHAT_MCH_ID"),
        serial_no=g("WECHAT_MCH_SERIAL_NO", "WECHAT_MCH_SERIAL_NO"),
        api_v3_key=g("WECHAT_PAY_KEY", "WECHAT_PAY_KEY"),
        private_key_pem=_resolve_pem(
            "WECHAT_MCH_PRIVATE_KEY", "WECHAT_MCH_PRIVATE_KEY_PATH", s
        ),
        platform_public_key_pem=_resolve_pem(
            "WECHAT_PLATFORM_PUBLIC_KEY", "WECHAT_PLATFORM_CERT_PATH", s
        ),
        notify_url=g("WECHAT_NOTIFY_URL", "WECHAT_NOTIFY_URL"),
    )


# ---------------------------------------------------------------------------
# ASN.1 / DER 解析（仅需 RSA 密钥结构）
# ---------------------------------------------------------------------------


def _der_read_tlv(data: bytes, i: int) -> tuple[int, bytes, int]:
    """读一个 TLV，返回 (tag, value, next_index)。"""
    if i >= len(data):
        raise WeChatPayError("DER 越界")
    tag = data[i]
    i += 1
    if i >= len(data):
        raise WeChatPayError("DER 长度缺失")
    first = data[i]
    i += 1
    if first & 0x80:
        n = first & 0x7F
        if n == 0 or i + n > len(data):
            raise WeChatPayError("DER 长度非法")
        length = int.from_bytes(data[i : i + n], "big")
        i += n
    else:
        length = first
    if i + length > len(data):
        raise WeChatPayError("DER 内容越界")
    return tag, data[i : i + length], i + length


def _der_children(value: bytes) -> list[tuple[int, bytes]]:
    """解析 SEQUENCE 的直接子 TLV。"""
    out: list[tuple[int, bytes]] = []
    i = 0
    while i < len(value):
        tag, val, i = _der_read_tlv(value, i)
        out.append((tag, val))
    return out


def _pem_to_der(pem: str) -> bytes:
    lines = [ln.strip() for ln in pem.strip().splitlines() if "-----" not in ln and ln.strip()]
    if not lines:
        raise WeChatPayError("PEM 内容为空")
    try:
        return base64.b64decode("".join(lines))
    except Exception as exc:  # noqa: BLE001
        raise WeChatPayError("PEM base64 解码失败") from exc


def _int_of(tag: int, value: bytes) -> int:
    if tag != 0x02:
        raise WeChatPayError("期望 INTEGER")
    return int.from_bytes(value, "big")


def _parse_rsa_private_pkcs1(der: bytes) -> tuple[int, int, int]:
    seq = _der_read_tlv(der, 0)
    if seq[0] != 0x30:
        raise WeChatPayError("私钥非 SEQUENCE")
    kids = _der_children(seq[1])
    # version, n, e, d, p, q, ...
    n = _int_of(*kids[1])
    e = _int_of(*kids[2])
    d = _int_of(*kids[3])
    return n, e, d


def _parse_rsa_public_spki(der: bytes) -> tuple[int, int]:
    seq = _der_read_tlv(der, 0)
    if seq[0] != 0x30:
        raise WeChatPayError("公钥非 SEQUENCE")
    kids = _der_children(seq[1])
    # AlgorithmIdentifier(SEQUENCE), BIT STRING(RSAPublicKey)
    bit = next((v for t, v in kids if t == 0x03), None)
    if bit is None or not bit:
        raise WeChatPayError("SPKI 缺 BIT STRING")
    inner = bit[1:] if bit[0] == 0 else bit  # 首字节为 unused-bits 计数
    return _parse_rsa_public_pkcs1(inner)


def _parse_rsa_public_pkcs1(der: bytes) -> tuple[int, int]:
    seq = _der_read_tlv(der, 0)
    if seq[0] != 0x30:
        raise WeChatPayError("公钥非 SEQUENCE")
    kids = _der_children(seq[1])
    return _int_of(*kids[0]), _int_of(*kids[1])


def load_private_key(pem: str) -> tuple[int, int, int]:
    """解析商户私钥 PEM（PKCS#8 / PKCS#1），返回 (n, e, d)。"""
    der = _pem_to_der(pem)
    if "BEGIN RSA PRIVATE KEY" in pem:
        return _parse_rsa_private_pkcs1(der)
    # PKCS#8: SEQUENCE { version, AlgorithmIdentifier, OCTET STRING(PKCS#1) }
    outer = _der_read_tlv(der, 0)
    kids = _der_children(outer[1])
    octet = next((v for t, v in kids if t == 0x04), None)
    if octet is None:
        raise WeChatPayError("PKCS#8 缺私钥 OCTET STRING")
    return _parse_rsa_private_pkcs1(octet)


def load_public_key(pem: str) -> tuple[int, int]:
    """解析公钥 PEM：支持 SPKI、PKCS#1、X.509 证书（启发式提取 SPKI）。"""
    der = _pem_to_der(pem)
    if "BEGIN RSA PUBLIC KEY" in pem:
        return _parse_rsa_public_pkcs1(der)
    if "BEGIN CERTIFICATE" in pem:
        return _extract_spki_from_cert(der)
    return _parse_rsa_public_spki(der)


def _extract_spki_from_cert(der: bytes) -> tuple[int, int]:
    """从 X.509 证书中提取 SubjectPublicKeyInfo（tbsCertificate 内）。"""
    outer = _der_read_tlv(der, 0)
    tbs = _der_read_tlv(outer[1], 0)
    for tag, val in _der_children(tbs[1]):
        if tag != 0x30:
            continue
        kids = _der_children(val)
        if len(kids) == 2 and kids[0][0] == 0x30 and kids[1][0] == 0x03:
            bit = kids[1][1]
            inner = bit[1:] if bit and bit[0] == 0 else bit
            return _parse_rsa_public_pkcs1(inner)
    raise WeChatPayError("证书中未找到 RSA 公钥")


# ---------------------------------------------------------------------------
# RSA PKCS#1 v1.5 + SHA-256 签名 / 验签
# ---------------------------------------------------------------------------

_SHA256_DIGEST_INFO_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")


def _emsa_pkcs1_v15(digest: bytes, em_len: int) -> bytes:
    t = _SHA256_DIGEST_INFO_PREFIX + digest
    if em_len < len(t) + 11:
        raise WeChatPayError("RSA 模长过小")
    ps = b"\xff" * (em_len - len(t) - 3)
    return b"\x00\x01" + ps + b"\x00" + t


def _rsa_sign(message: bytes, pem: str) -> str:
    n, _e, d = load_private_key(pem)
    k = (n.bit_length() + 7) // 8
    em = _emsa_pkcs1_v15(hashlib.sha256(message).digest(), k)
    sig = pow(int.from_bytes(em, "big"), d, n).to_bytes(k, "big")
    return base64.b64encode(sig).decode()


def _rsa_verify(message: bytes, signature_b64: str, pem: str) -> bool:
    try:
        n, e = load_public_key(pem)
        sig = base64.b64decode(signature_b64)
        k = (n.bit_length() + 7) // 8
        if len(sig) != k:
            return False
        m = pow(int.from_bytes(sig, "big"), e, n).to_bytes(k, "big")
        return m == _emsa_pkcs1_v15(hashlib.sha256(message).digest(), k)
    except Exception:  # noqa: BLE001 —— 任何解析/解码异常均视为验签失败
        return False


def _build_ts_message(method: str, url_path: str, timestamp: str, nonce: str, body: str) -> str:
    return f"{method.upper()}\n{url_path}\n{timestamp}\n{nonce}\n{body}\n"


def build_authorization(
    method: str,
    url_path: str,
    body: str = "",
    *,
    cfg: WeChatPayConfig | None = None,
    timestamp: str | None = None,
    nonce: str | None = None,
) -> str:
    """构造 WECHATPAY2-SHA256-RSA2048 Authorization 头值。"""
    cfg = cfg or load_config()
    ts = timestamp or str(int(time.time()))
    nc = nonce or secrets.token_hex(16)
    message = _build_ts_message(method, url_path, ts, nc, body)
    signature = _rsa_sign(message.encode(), cfg.private_key_pem)
    return (
        f'{AUTH_SCHEMA} mchid="{cfg.mch_id}",nonce_str="{nc}",'
        f'signature="{signature}",timestamp="{ts}",serial_no="{cfg.serial_no}"'
    )


def verify_notify_signature(
    timestamp: str, nonce: str, body: str, signature: str, public_key_pem: str
) -> bool:
    """回调报文验签：报文为 `timestamp\\nnonce\\nbody\\n`，RSA-SHA256。"""
    message = f"{timestamp}\n{nonce}\n{body}\n".encode()
    return _rsa_verify(message, signature, public_key_pem)


def verify_authorization(
    authorization: str, method: str, url_path: str, body: str, public_key_pem: str
) -> bool:
    """校验 Authorization 头（供单测/网关复用）。"""
    try:
        _, params = authorization.split(" ", 1)
        kv = dict(item.split("=", 1) for item in params.split(","))
        kv = {k: v.strip('"') for k, v in kv.items()}
        message = _build_ts_message(
            method, url_path, kv["timestamp"], kv["nonce_str"], body
        )
        return _rsa_verify(message.encode(), kv["signature"], public_key_pem)
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# AES-256-GCM（纯标准库实现，用于回调 resource 解密）
# ---------------------------------------------------------------------------

_RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36, 0x6C, 0xD8, 0xAB, 0x4D]


def _xtime(a: int) -> int:
    a <<= 1
    if a & 0x100:
        a ^= 0x11B
    return a & 0xFF


def _gf_mul(a: int, b: int) -> int:
    p = 0
    for _ in range(8):
        if b & 1:
            p ^= a
        b >>= 1
        a = _xtime(a)
    return p


def _gf_inv(a: int) -> int:
    if a == 0:
        return 0
    result, base, exp = 1, a, 254
    while exp:
        if exp & 1:
            result = _gf_mul(result, base)
        base = _gf_mul(base, base)
        exp >>= 1
    return result


def _rotl8(x: int, n: int) -> int:
    return ((x << n) | (x >> (8 - n))) & 0xFF


def _build_sbox() -> list[int]:
    box = []
    for i in range(256):
        inv = _gf_inv(i)
        y = inv
        for n in (1, 2, 3, 4):
            y ^= _rotl8(inv, n)
        box.append((y ^ 0x63) & 0xFF)
    return box


_SBOX = _build_sbox()


def _key_expansion(key: bytes) -> tuple[list[list[int]], int]:
    nk = len(key) // 4
    nr = nk + 6
    words = [list(key[4 * i : 4 * i + 4]) for i in range(nk)]
    for i in range(nk, 4 * (nr + 1)):
        temp = list(words[i - 1])
        if i % nk == 0:
            temp = [_SBOX[b] for b in temp[1:] + temp[:1]]
            temp[0] ^= _RCON[i // nk - 1]
        elif nk > 6 and i % nk == 4:
            temp = [_SBOX[b] for b in temp]
        words.append([words[i - nk][j] ^ temp[j] for j in range(4)])
    return words, nr


def _add_round_key(state: list[int], words: list[list[int]], rnd: int) -> None:
    for c in range(4):
        for r in range(4):
            state[4 * c + r] ^= words[4 * rnd + c][r]


def _sub_bytes(state: list[int]) -> None:
    for i in range(16):
        state[i] = _SBOX[state[i]]


def _shift_rows(state: list[int]) -> None:
    for r in range(1, 4):
        row = [state[4 * c + r] for c in range(4)]
        row = row[r:] + row[:r]
        for c in range(4):
            state[4 * c + r] = row[c]


def _mix_columns(state: list[int]) -> None:
    for c in range(4):
        i = 4 * c
        a0, a1, a2, a3 = state[i], state[i + 1], state[i + 2], state[i + 3]
        state[i] = _gf_mul(a0, 2) ^ _gf_mul(a1, 3) ^ a2 ^ a3
        state[i + 1] = a0 ^ _gf_mul(a1, 2) ^ _gf_mul(a2, 3) ^ a3
        state[i + 2] = a0 ^ a1 ^ _gf_mul(a2, 2) ^ _gf_mul(a3, 3)
        state[i + 3] = _gf_mul(a0, 3) ^ a1 ^ a2 ^ _gf_mul(a3, 2)


def _encrypt_block(block: bytes, key: bytes) -> bytes:
    words, nr = _key_expansion(key)
    state = list(block)
    _add_round_key(state, words, 0)
    for rnd in range(1, nr):
        _sub_bytes(state)
        _shift_rows(state)
        _mix_columns(state)
        _add_round_key(state, words, rnd)
    _sub_bytes(state)
    _shift_rows(state)
    _add_round_key(state, words, nr)
    return bytes(state)


def _gf128_mul(x: int, y: int) -> int:
    z, v = 0, y
    for i in range(128):
        if (x >> (127 - i)) & 1:
            z ^= v
        if v & 1:
            v = (v >> 1) ^ (0xE1 << 120)
        else:
            v >>= 1
    return z


def _ghash(h: int, data: bytes) -> int:
    y = 0
    for i in range(0, len(data), 16):
        y ^= int.from_bytes(data[i : i + 16], "big")
        y = _gf128_mul(y, h)
    return y


def _pad16(data: bytes) -> bytes:
    return data + b"\x00" * ((16 - len(data) % 16) % 16)


def _inc32(block: bytes) -> bytes:
    prefix, counter = block[:12], int.from_bytes(block[12:], "big")
    return prefix + ((counter + 1) % (1 << 32)).to_bytes(4, "big")


def _gcm_j0(h: int, nonce: bytes) -> bytes:
    if len(nonce) == 12:
        return nonce + b"\x00\x00\x00\x01"
    tail = _pad16(nonce) + b"\x00" * 8 + (len(nonce) * 8).to_bytes(8, "big")
    return _ghash(h, tail).to_bytes(16, "big")


def _gcm_tag(key: bytes, h: int, j0: bytes, aad: bytes, ciphertext: bytes) -> bytes:
    lengths = (len(aad) * 8).to_bytes(8, "big") + (len(ciphertext) * 8).to_bytes(8, "big")
    s = _ghash(h, _pad16(aad) + _pad16(ciphertext) + lengths)
    return bytes(
        a ^ b
        for a, b in zip(_encrypt_block(j0, key), s.to_bytes(16, "big"), strict=True)
    )


def aes_gcm_decrypt(
    key: bytes, nonce: bytes, aad: bytes, data: bytes, tag: bytes | None = None
) -> bytes:
    """AES-256-GCM 解密；data 可含尾部 16 字节 tag，亦可用 tag 参数单列。"""
    if tag is None:
        if len(data) < 16:
            raise WeChatPayError("GCM 密文过短")
        data, tag = data[:-16], data[-16:]
    h = int.from_bytes(_encrypt_block(b"\x00" * 16, key), "big")
    j0 = _gcm_j0(h, nonce)
    counter = _inc32(j0)
    plain = bytearray()
    for i in range(0, len(data), 16):
        ks = _encrypt_block(counter, key)
        chunk = data[i : i + 16]
        plain.extend(x ^ y for x, y in zip(chunk, ks, strict=False))
        counter = _inc32(counter)
    expected = _gcm_tag(key, h, j0, aad, data)
    if not secrets.compare_digest(expected, tag):
        raise WeChatPayError("GCM 认证失败（tag 不匹配，报文可能被篡改）")
    return bytes(plain)


def decrypt_resource(
    ciphertext: str, nonce: str, associated_data: str = "", api_v3_key: str = ""
) -> str:
    """解密回调 resource（base64 密文含 tag），返回明文字符串。"""
    key = api_v3_key.encode()
    if len(key) != 32:
        raise WeChatPayError("APIv3 密钥必须为 32 字节")
    try:
        raw = base64.b64decode(ciphertext)
    except Exception as exc:  # noqa: BLE001
        raise WeChatPayError("resource 密文 base64 解码失败") from exc
    plain = aes_gcm_decrypt(key, nonce.encode(), associated_data.encode(), raw)
    return plain.decode("utf-8")


# ---------------------------------------------------------------------------
# 回调解析（验签 + 解密）
# ---------------------------------------------------------------------------


def parse_notify(headers: dict[str, str], body: str, cfg: WeChatPayConfig | None = None) -> dict:
    """校验回调签名并解密 resource，返回明文业务 JSON。

    headers 大小写不敏感；缺 Key 时抛 WeChatPayError（由调用方决定降级/拒绝）。
    """
    cfg = cfg or load_config()
    lower = {k.lower(): v for k, v in headers.items()}
    timestamp = lower.get("wechatpay-timestamp", "")
    nonce = lower.get("wechatpay-nonce", "")
    signature = lower.get("wechatpay-signature", "")
    if not (timestamp and nonce and signature):
        raise WeChatPayError("回调缺少 WECHATPAY-* 验签头")
    if not verify_notify_signature(
        timestamp, nonce, body, signature, cfg.platform_public_key_pem
    ):
        raise WeChatPayError("回调解密前验签失败")
    payload = json.loads(body)
    resource = payload.get("resource") or {}
    plaintext = decrypt_resource(
        resource.get("ciphertext", ""),
        resource.get("nonce", ""),
        resource.get("associated_data", ""),
        cfg.api_v3_key,
    )
    return json.loads(plaintext)


# ---------------------------------------------------------------------------
# JSAPI 预下单（真实接入骨架 + 无密钥降级）
# ---------------------------------------------------------------------------


@dataclass
class PrepayResult:
    """预下单结果：pay_params 供小程序 wx.requestPayment；degraded 标记是否为降级占位。"""

    pay_params: dict[str, Any]
    degraded: bool
    reason: str = ""


def _jsapi_pay_sign(cfg: WeChatPayConfig, timestamp: str, nonce: str, package: str) -> str:
    message = f"{cfg.appid}\n{timestamp}\n{nonce}\n{package}\n".encode()
    return _rsa_sign(message, cfg.private_key_pem)


def _degraded_params(order: Any) -> dict[str, Any]:
    """无密钥降级：本地占位参数（明确标记 degraded，绝不冒充真实签名）。"""
    return {
        "timeStamp": str(int(time.time())),
        "nonceStr": secrets.token_hex(16),
        "package": f"prepay_id=degraded_{getattr(order, 'order_no', '')}",
        "signType": "RSA",
        "paySign": "",
        "degraded": True,
    }


async def prepare_payment(order: Any, settings: Settings | None = None) -> PrepayResult:
    """JSAPI 预下单：已配置 → 真实统一下单；未配置 → 降级占位（可判别）。"""
    cfg = load_config(settings)
    if not cfg.configured:
        return PrepayResult(
            pay_params=_degraded_params(order),
            degraded=True,
            reason="微信支付未配置（缺 mch_id/serial_no/私钥/APIv3 密钥），降级为本地占位参数",
        )

    payload = {
        "appid": cfg.appid,
        "mchid": cfg.mch_id,
        "description": f"订单 {order.order_no}",
        "out_trade_no": order.order_no,
        "notify_url": cfg.notify_url,
        "amount": {"total": int(round(float(order.pay_amount) * 100)), "currency": "CNY"},
        "payer": {"openid": getattr(order, "openid", "") or ""},
    }
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    authorization = build_authorization("POST", JSAPI_PATH, body, cfg=cfg)

    import httpx  # 延迟导入，避免无网络场景的模块加载副作用

    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.post(
            JSAPI_URL,
            content=body.encode(),
            headers={
                "Authorization": authorization,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
    if resp.status_code != 200:
        raise WeChatPayError(f"统一下单失败 HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    prepay_id = data.get("prepay_id")
    if not prepay_id:
        raise WeChatPayError("统一下单响应缺少 prepay_id")

    ts = str(int(time.time()))
    nonce = secrets.token_hex(16)
    package = f"prepay_id={prepay_id}"
    return PrepayResult(
        pay_params={
            "timeStamp": ts,
            "nonceStr": nonce,
            "package": package,
            "signType": "RSA",
            "paySign": _jsapi_pay_sign(cfg, ts, nonce, package),
        },
        degraded=False,
    )
