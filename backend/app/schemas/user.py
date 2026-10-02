"""用户域 schema：/api/auth/me（UserDetail/UserBenefit）、/api/user/avatar（AvatarUpdateIn）。"""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class UserBenefit(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tier: int = 0  # 0基础 1进阶 2高级 3终身
    ai_times_left: int = 0


class UserDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nickname: str
    avatar_url: Optional[str] = None
    gender: Optional[int] = None  # 0未知 1男 2女
    benefit: Optional[UserBenefit] = None


class AvatarUpdateIn(BaseModel):
    """更新当前用户头像：COS 公开读 URL（前端直传成功后回填）。"""

    model_config = ConfigDict(from_attributes=True)

    avatar_url: str = Field(min_length=1, max_length=512)
