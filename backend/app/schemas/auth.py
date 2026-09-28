"""认证域 schema（openapi: /api/auth/*，LoginRequest/LoginData/UserBrief）。"""


from pydantic import BaseModel, ConfigDict


class LoginRequest(BaseModel):
    """POST /api/auth/login：微信 wx.login code 换 token。"""

    model_config = ConfigDict(from_attributes=True)

    code: str
    encrypted_data: str | None = None
    iv: str | None = None


class UserBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nickname: str
    avatar_url: str | None = None


class LoginData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    token: str
    refresh_token: str
    is_new: bool
    need_profile: bool  # 需要引导补全身体档案
    user: UserBrief


class RefreshIn(BaseModel):
    """POST /api/auth/refresh：refresh_token 换新 access。"""

    model_config = ConfigDict(from_attributes=True)

    refresh_token: str


class RefreshData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    token: str
    refresh_token: str
