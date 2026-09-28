"""认证域接口（openapi: /api/auth/login、/api/auth/me）。"""

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, get_current_user, get_request_id
from app.schemas import Envelope, LoginData, LoginRequest, UserBenefit, UserDetail
from app.schemas.common import ok
from app.services import auth_service

router = APIRouter(tags=["认证"])


@router.post("/auth/login", response_model=Envelope[LoginData], summary="微信登录，code 换 token")
async def auth_login(
    payload: LoginRequest, request_id: str | None = Depends(get_request_id)
) -> Envelope[LoginData]:
    """wx.login code → code2session 换 openid（密钥未配置走 mock）→ 签发 JWT。"""
    data = await auth_service.login(payload.code)
    return ok(data, request_id=request_id)


@router.get("/auth/me", response_model=Envelope[UserDetail], summary="当前用户")
async def auth_me(
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[UserDetail]:
    # TODO(Phase1): 查库返回真实档案与权益（P0 stub 对齐 mock 数据）
    data = UserDetail(
        id=user.id,
        nickname=f"减友{user.id % 10000:04d}",
        gender=1,
        benefit=UserBenefit(tier=0, ai_times_left=9),
    )
    return ok(data, request_id=request_id)
