"""安全原语：JWT 签发/校验（PyJWT）+ 密码哈希（hashlib.pbkdf2_hmac）+ 后台口令策略。"""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

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


# ---- 管理后台口令策略（原 backend/scripts/init_admin.py 内联逻辑，账号管理接口复用） ----

# 弱口令门槛：低于此长度一律拒绝（后端 Settings 默认口令 admin123456 只有 11 位）。
MIN_ADMIN_PASSWORD_LENGTH = 12

# 仓库里出现过的公开口令黑名单：这些值的长度都过了长度门槛，单靠长度检查拦不住，
# 一旦建号就等于把凭据写进公开仓库。前两个是 CI/deploy workflow 里曾硬编码的兜底串
# （已删除，保留在此防复发）；后两个是 003 种子文件里 ops / merchant1 的公开种子口令。
_KNOWN_PUBLIC_PASSWORDS = frozenset(
    {
        "ci-only-not-a-real-secret-0001",
        "deploy-only-not-a-real-secret-0001",
        "Admin@123456",
        "Merchant@123",
    }
)

# 仓库根（backend/app/core/ → backend/ → 根）。容器镜像只 COPY backend/，
# 故 .env.example 在容器里不存在 → 占位串比对那条自动跳过（`change-me` 前缀那条仍兜住）。
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _read_env_example_password() -> str:
    """读 .env.example 的 ADMIN_INIT_PASSWORD 原值（不硬编码占位串进代码）。

    文件不存在（容器镜像不含）或键缺失时返回空串 → 该条比对自动跳过。
    """
    path = _REPO_ROOT / ".env.example"
    try:
        content = path.read_text(encoding="utf-8-sig")
    except OSError:
        return ""
    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() == "ADMIN_INIT_PASSWORD":
            return value.strip().strip('"').strip("'")
    return ""


def reject_weak_password(password: str) -> str:
    """后台账号口令策略：返回拒绝原因，合格返回空串。

    供账号管理接口与 init_admin.py 共用——占位串（Settings 出厂默认、.env.example
    原值、change-me 前缀）、仓库公开口令黑名单、长度不足一律拒绝，防止把仓库内
    可读的字符串变成可用凭据。
    """
    default_password = Settings.model_fields["ADMIN_INIT_PASSWORD"].default
    if default_password and password == default_password:
        return "取值为后端 Settings.ADMIN_INIT_PASSWORD 的出厂默认口令"

    example_password = _read_env_example_password()
    if example_password and password == example_password:
        return "取值与 .env.example 的 ADMIN_INIT_PASSWORD 占位串相同"

    if password.lower().startswith("change-me"):
        return "取值是 change-me* 占位串"

    if password in _KNOWN_PUBLIC_PASSWORDS:
        return f"取值是仓库内公开口令（{password}），任何读得到仓库的人都能用它登录"

    if len(password) < MIN_ADMIN_PASSWORD_LENGTH:
        return f"长度不足 {MIN_ADMIN_PASSWORD_LENGTH} 位"

    return ""
