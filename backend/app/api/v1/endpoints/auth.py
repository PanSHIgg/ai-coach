"""认证域接口（openapi: /api/auth/login、/api/auth/me、/api/auth/refresh）。"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_current_user, get_request_id
from app.db.session import get_db
from app.schemas import (
    Envelope,
    LoginData,
    LoginRequest,
    RefreshData,
    RefreshIn,
    UserDetail,
)
from app.schemas.common import ok
from app.services import auth_service, user_service

router = APIRouter(tags=["认证"])


@router.post("/auth/login", response_model=Envelope[LoginData], summary="微信登录，code 换 token")
async def auth_login(
    payload: LoginRequest,
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[LoginData]:
    """wx.login code → code2session 换 openid（无微信凭证即 1001 失败）→ upsert 用户 → 签发 JWT。"""
    data = await auth_service.login(session, payload.code)
    return ok(data, request_id=request_id)


@router.get("/auth/me", response_model=Envelope[UserDetail], summary="当前用户")
async def auth_me(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[UserDetail]:
    """查真实 user + body_profile + user_benefit；无档案时字段合理缺省。"""
    data = await user_service.get_me(session, user.id)
    return ok(data, request_id=request_id)


@router.post("/auth/refresh", response_model=Envelope[RefreshData], summary="刷新 access token")
async def auth_refresh(
    payload: RefreshIn,
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[RefreshData]:
    """refresh_token（typ=refresh）换发新 access(2h)+refresh(7d)；失败 1001。"""
    data = await auth_service.refresh(session, payload.refresh_token)
    return ok(data, request_id=request_id)
