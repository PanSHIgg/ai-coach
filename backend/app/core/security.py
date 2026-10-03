"""安全原语：JWT 签发/校验（PyJWT）+ 密码哈希（hashlib.pbkdf2_hmac）。"""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import Settings, get_settings
from app.core.errors import AppException
from app.schemas.common import ErrorCode

_PBKDF2_ITERATIONS = 600_000  # OWASP 2023 建议；存储格式含 iterations，旧哈希仍可校验


# ---- 密码哈希（管理后台登录用；微信登录无密码） ----

def hash_password(password: str, iterations: int = _PBKDF2_ITERATIONS) -> str:
    """返回 pbkdf2_sha256$<iter>$<salt_hex>$<hash_hex>。"""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, hashed: str) -> bool:
    """恒定时间比较，格式不符或哈希畸形一律返回 False。

    刻意不抛异常：hash_password 的产物格式固定，但库里的 password_hash 也可能被
    外部写坏（手工改库/迁移失误/截断），此时登录与初始化脚本应当当作"密码不匹配"
    降级处理，而不是抛 ValueError/OverflowError/AttributeError 变成 500。
    """
    try:
        algorithm, iterations, salt_hex, digest_hex = hashed.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations)
        )
    except (ValueError, TypeError, AttributeError, OverflowError):
        # ValueError：段数不对、非数字 iterations、坏 hex 盐；
        # OverflowError：iterations 大到 int 转换溢出（如 1e11）；
        # AttributeError/TypeError：hashed 为 None 或非字符串。
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


# ---- JWT（access 2h / refresh 7d） ----

def _encode_token(
    sub: str, token_type: str, ttl: timedelta, settings: Settings, **claims: object
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": sub,
        "typ": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
        **claims,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_access_token(sub: str, settings: Settings | None = None, **claims: object) -> str:
    s = settings or get_settings()
    return _encode_token(sub, "access", timedelta(hours=s.JWT_ACCESS_EXPIRE_HOURS), s, **claims)


def create_refresh_token(sub: str, settings: Settings | None = None, **claims: object) -> str:
    s = settings or get_settings()
    return _encode_token(sub, "refresh", timedelta(days=s.JWT_REFRESH_EXPIRE_DAYS), s, **claims)


def decode_token(
    token: str, expected_type: str = "access", expected_dom: str | None = None
) -> dict:
    """校验并解码 JWT；失败统一抛 1001（未登录/Token 失效）。

    expected_dom 非空时强校验 dom claim（token 域隔离：admin 域与 C 端域互不通用）。
    """
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise AppException(ErrorCode.UNAUTHORIZED) from exc
    except jwt.InvalidTokenError as exc:
        raise AppException(ErrorCode.UNAUTHORIZED) from exc
    if payload.get("typ") != expected_type:
        raise AppException(ErrorCode.UNAUTHORIZED)
    if expected_dom is not None and payload.get("dom") != expected_dom:
        raise AppException(ErrorCode.UNAUTHORIZED)
    return payload
