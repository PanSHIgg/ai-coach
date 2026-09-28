"""用户域 schema（openapi: /api/auth/me → UserDetail/UserBenefit）。"""

from typing import Optional

from pydantic import BaseModel, ConfigDict


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
