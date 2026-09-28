"""公共依赖：JWT 认证（get_current_user）与 request_id 提取。"""

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppException
from app.core.security import decode_token
from app.db.session import get_db
from app.models import User
from app.schemas.common import ErrorCode

_bearer_scheme = HTTPBearer(auto_error=False)


class CurrentUser(BaseModel):
    """JWT 解析出的用户 stub（Phase1 接 user 表）。"""

    id: int
    openid: str | None = None


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    session: AsyncSession = Depends(get_db),
) -> CurrentUser:
    """Bearer JWT → 用户 stub；缺失/无效/指向已删用户统一 1001。

    按 User.id 主键校验存在性：避免已删用户的 token 在写接口触发外键 IntegrityError → 500。
    """
    if credentials is None or not credentials.credentials:
        raise AppException(ErrorCode.UNAUTHORIZED)
    payload = decode_token(credentials.credentials, expected_type="access")
    try:
        user_id = int(payload.get("sub", ""))
    except (TypeError, ValueError) as exc:
        raise AppException(ErrorCode.UNAUTHORIZED) from exc
    exists = await session.scalar(select(User.id).where(User.id == user_id))
    if exists is None:
        raise AppException(ErrorCode.UNAUTHORIZED)
    return CurrentUser(id=user_id, openid=payload.get("openid"))


def get_request_id(request: Request) -> str | None:
    """取中间件注入的 request_id（envelope 回显用）。"""
    return getattr(request.state, "request_id", None)
