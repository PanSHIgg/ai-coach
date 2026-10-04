"""社区域 schema（openapi: /api/invite*、/api/community/*、Phase 4 BE7a/BE7b/BE7c）。"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .auth import UserBrief
from .common import PageMeta

# ---- 邀请 ----

class InviteIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    invite_code: Optional[str] = None  # 缺省=创建邀请码；带值=绑定邀请关系
    device_id: Optional[str] = None  # 可选设备标识：同设备只计 1 次（重复 → 4102）


class InviteData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    bound: bool
    invite_code: Optional[str] = None  # 创建时返回
    poster_url: Optional[str] = None  # 邀请海报地址


class NextTier(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    need: int  # 距下一档还差人数
    reward: str  # 如 进阶版20次/日 / 高级版40次/日 / 终身版不限次


class BenefitInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tier: int  # 0基础 1进阶 2高级 3终身（权益无期限，不回收）


class InviteProgressData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    invitee_count: int
    next_tier: NextTier
    benefit: BenefitInfo
    poster_url: Optional[str] = None


# ---- 社区动态（BE7a）----

class CommunityPostIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    content: str = Field(min_length=1, max_length=2000)
    images: list[str] = []
    anonymous: bool = False
    title: Optional[str] = Field(default=None, max_length=256)
    post_type: int = Field(default=1, ge=1, le=3)  # 1普通 2经验 3打卡


class CommunityPostCreated(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    audit_status: int = 1  # 0待审（进审核队列）1通过


class CommunityPostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user: UserBrief
    title: Optional[str] = None
    content: str
    images: list[str] = []
    post_type: int = 1
    like_count: int = 0
    comment_count: int = 0
    anonymous: bool = False
    liked: bool = False  # 当前用户是否已赞
    created_at: datetime


class PostPageData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[CommunityPostOut]
    page: PageMeta


class PostDeleteData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    deleted: bool = True


class LikeData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    post_id: int
    liked: bool
    like_count: int


# ---- 评论 ----

class CommunityCommentIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    content: str = Field(min_length=1, max_length=500)
    anonymous: bool = False


class CommunityCommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user: UserBrief
    content: str
    anonymous: bool = False
    created_at: datetime


class CommentPageData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[CommunityCommentOut]
    page: PageMeta


# ---- 监督搭子（BE7b）----

class SuperviseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    partner: UserBrief
    status: int  # 1生效 0解除
    days: int
    created_at: datetime


class SuperviseMatchIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    partner_id: Optional[int] = None  # 缺省=系统匹配一个未配对的减友


class SuperviseRemindData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    supervise_id: int
    reminded: bool = True
    message: str


class SuperviseRecordItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    date: str  # YYYY-MM-DD
    intake: float  # 摄入 kcal
    steps: int
    deficit: float  # 负值为缺口


class SuperviseRecordsData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    supervise_id: int
    partner: UserBrief
    items: list[SuperviseRecordItem]


# ---- 兴趣社群（BE7b）----

class GroupItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    category: Optional[str] = None
    member_count: int = 0
    city: Optional[str] = None
    created_at: datetime


class GroupPageData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[GroupItem]
    page: PageMeta


class GroupJoinData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    group_id: int
    joined: bool = True
    member_count: int


class GroupCheckinData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    group_id: int
    checked: bool = True
    checkin_days: int
    post_id: Optional[int] = None  # 打卡以 post_type=3 动态形式沉淀


# ---- 约战（BE7b）----

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
    creator_id: Optional[int] = None
    # 当前用户是否在成员表里（发起人建战即入表、退出即出表）；未登录调用恒为 False
    joined: bool = False
    # 当前用户是否可删除该约战（仅发起人本人）
    can_delete: bool = False


class BattlePageData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[BattleItem]
    page: PageMeta


class BattleCreateIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    title: str = Field(min_length=1, max_length=256)
    sport_name: Optional[str] = Field(default=None, max_length=64)
    merchant_id: Optional[int] = None  # 关联场馆券
    city: Optional[str] = Field(default=None, max_length=64)
    lat: Optional[float] = None  # LBS 匹配用
    lng: Optional[float] = None
    meet_at: datetime
    need_count: int = Field(default=2, ge=2, le=50)


class BattleJoinIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    battle_id: int


class BattleJoinData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    battle_id: int
    joined: bool = True
    join_count: int


class BattleQuitData(BaseModel):
    """退出约战结果：joined 恒为 False，join_count 为退出后的最新人数。"""

    model_config = ConfigDict(from_attributes=True)

    battle_id: int
    joined: bool = False
    join_count: int


class BattleDeleteData(BaseModel):
    """删除约战结果（仅发起人）：约战与其成员行一并移除。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    deleted: bool = True


# ---- 挑战赛（BE7b）----

class ChallengeItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    badge_image: Optional[str] = None
    join_count: int = 0
    status: int  # 1进行中 2结束
    joined: bool = False


class ChallengePageData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[ChallengeItem]
    page: PageMeta


class ChallengeJoinData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    challenge_id: int
    joined: bool = True
    join_count: int


class LeaderboardEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rank: int
    user: UserBrief
    score: float


class ChallengeLeaderboardData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    challenge_id: int
    items: list[LeaderboardEntry]


class LeaderboardData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    period_type: int  # 1日榜 2周榜 3月榜
    period_key: str
    items: list[LeaderboardEntry]


# ---- 同款减友经验（动态 post_type=2 视图）----

class ExperienceItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user: UserBrief
    title: Optional[str] = None
    content: str
    like_count: int = 0
    created_at: datetime


class ExperiencePageData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[ExperienceItem]
    page: PageMeta
