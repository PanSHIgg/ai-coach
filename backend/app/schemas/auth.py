"""认证域 schema（openapi: /api/auth/*，LoginRequest/LoginData/UserBrief）。"""

from typing import Optional

from pydantic import BaseModel, ConfigDict


class LoginRequest(BaseModel):
    """POST /api/auth/login：微信 wx.login code 换 token。"""

    model_config = ConfigDict(from_attributes=True)

    code: str
    encrypted_data: Optional[str] = None
    iv: Optional[str] = None


class UserBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nickname: str
    avatar_url: Optional[str] = None


class LoginData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    token: str
    refresh_token: str
    is_new: bool
    need_profile: bool  # 需要引导补全身体档案
    user: UserBrief
