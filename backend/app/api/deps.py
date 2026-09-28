"""公共依赖：JWT 认证（get_current_user）与 request_id 提取。"""

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.core.errors import AppException
from app.core.security import decode_token
from app.schemas.common import ErrorCode

_bearer_scheme = HTTPBearer(auto_error=False)


class CurrentUser(BaseModel):
    """JWT 解析出的用户 stub（P0 不查库；Phase1 接 user 表）。"""

    id: int
    openid: str | None = None


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> CurrentUser:
    """Bearer JWT → 用户 stub；缺失/无效统一 1001。"""
    if credentials is None or not credentials.credentials:
        raise AppException(ErrorCode.UNAUTHORIZED)
    payload = decode_token(credentials.credentials, expected_type="access")
    try:
        user_id = int(payload.get("sub", ""))
    except (TypeError, ValueError) as exc:
        raise AppException(ErrorCode.UNAUTHORIZED) from exc
    return CurrentUser(id=user_id, openid=payload.get("openid"))


def get_request_id(request: Request) -> str | None:
    """取中间件注入的 request_id（envelope 回显用）。"""
    return getattr(request.state, "request_id", None)
