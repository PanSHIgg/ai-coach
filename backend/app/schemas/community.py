"""社区域 schema（openapi: /api/invite*、/api/community/*）。"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .auth import UserBrief
from .common import PageMeta


# ---- 邀请 ----

class InviteIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    invite_code: Optional[str] = None  # 缺省=创建邀请码；带值=绑定邀请关系


class InviteData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    bound: bool
    invite_code: Optional[str] = None  # 创建时返回
    poster_url: Optional[str] = None  # 邀请海报地址


class NextTier(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    need: int  # 距下一档还差人数
    reward: str  # 如 进阶版90天


class BenefitInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tier: int  # 0基础 1进阶 2高级 3终身
    valid_to: Optional[datetime] = None


class InviteProgressData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    invitee_count: int
    next_tier: NextTier
    benefit: BenefitInfo
    poster_url: Optional[str] = None


# ---- 社区动态 ----

class CommunityPostIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    content: str = Field(min_length=1, max_length=2000)
    images: list[str] = []
    anonymous: bool = False


class CommunityPostCreated(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int


class CommunityPostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user: UserBrief
    content: str
    images: list[str] = []
    like_count: int = 0
    comment_count: int = 0
    created_at: datetime


class PostPageData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[CommunityPostOut]
    page: PageMeta


# ---- 约战 ----

class BattleItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    sport_name: Optional[str] = None
    merchant_id: Optional[int] = None
    city: Optional[str] = None
    meet_at: datetime
    need_count: int
    join_count: int
    status: int  # 1招募中 2满员 3进行中 4结束


class BattlePageData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[BattleItem]
    page: PageMeta


class BattleJoinIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    battle_id: int


class BattleJoinData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    battle_id: int
    joined: bool = True
    join_count: int
