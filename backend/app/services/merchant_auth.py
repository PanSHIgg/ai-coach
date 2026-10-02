"""商家自助后台鉴权（G11）：口令校验 + 商家 token 签发/解析。

设计口径（商家 token 独立于用户 JWT / admin 域）：
- 口令哈希：复用 `core.security` 的 PBKDF2 原语（`hash_password`/`verify_password`，不改 core）；
  另兼容 bcrypt 哈希（`$2a$/$2b$/$2y$` 前缀，仅当运行环境安装了 `bcrypt` 时校验）。
- token：复用 `core.security.create_access_token`（同密钥/算法），claims 固定为
  `dom="merchant"`、`role="merchant"`、`merchant_id=<id>`、`account_id=<登录账号 id>`；
  `sub=f"merchant:{id}"` 刻意非纯数字，避免被 C 端 `get_current_user` 误解析成 user_id。
- 校验：`decode_token(expected_type="access", expected_dom="merchant")`，缺失/过期/域不符统一 1001。

【假设】商家账号来源：`merchant_account` 表由平台侧开通（本波契约未提供注册/开通接口），
测试与运维直接落库（password_hash 用 `hash_password` 生成）。登录失败不外泄账号是否存在。
"""

from __future__ import annotations

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import AppException
from app.core.security import (
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models import MerchantAccount
from app.schemas.common import ErrorCode

# 商家账号启用状态
ACCOUNT_STATUS_ACTIVE = 1

_BCRYPT_PREFIXES = ("$2a$", "$2b$", "$2y$")


class MerchantPrincipal(BaseModel):
    """商家 token 解析出的身份（merchant_id 为业务归属）。"""

    merchant_id: int
    account_id: int | None = None
    username: str | None = None


def verify_merchant_password(password: str, hashed: str) -> bool:
    """校验商家口令：bcrypt 前缀走 bcrypt（若已安装），否则走 core PBKDF2 校验。"""
    if hashed.startswith(_BCRYPT_PREFIXES):
        try:
            import bcrypt  # noqa: PLC0415 - 可选依赖，缺失时降级为校验失败
        except ImportError:
            return False
        try:
            return bool(bcrypt.checkpw(password.encode(), hashed.encode()))
        except ValueError:
            return False
    return verify_password(password, hashed)


def create_merchant_token(
    merchant_id: int,
    account_id: int | None = None,
    settings: Settings | None = None,
) -> tuple[str, int]:
    """签发商家 token，返回 `(token, expires_in 秒)`。"""
    s = settings or get_settings()
    token = create_access_token(
        f"merchant:{merchant_id}",
        dom="merchant",
        role="merchant",
        merchant_id=merchant_id,
        account_id=account_id,
    )
    return token, int(s.JWT_ACCESS_EXPIRE_HOURS) * 3600


def decode_merchant_token(token: str) -> dict:
    """校验并解码商家 token；失败统一 1001。"""
    return decode_token(token, expected_type="access", expected_dom="merchant")


async def authenticate(
    session: AsyncSession, username: str, password: str
) -> MerchantAccount:
    """按 username 查启用账号并校验口令；失败统一 1001（不区分账号是否存在）。"""
    account = (
        await session.execute(
            select(MerchantAccount).where(
                MerchantAccount.username == username,
                MerchantAccount.status == ACCOUNT_STATUS_ACTIVE,
            )
        )
    ).scalar_one_or_none()
    if account is None or not verify_merchant_password(password, account.password_hash):
        raise AppException(ErrorCode.UNAUTHORIZED)
    return account


__all__ = [
    "ACCOUNT_STATUS_ACTIVE",
    "MerchantPrincipal",
    "authenticate",
    "create_merchant_token",
    "decode_merchant_token",
    "hash_password",
    "verify_merchant_password",
]