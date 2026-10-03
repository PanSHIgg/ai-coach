"""真人教练工单域 schema（openapi: /api/coach/*）。

契约对齐：`#/components/schemas/Coach*`。行级隔离硬约束体现在**数据契约**层面——
教练域出参一律自带 coach_id，教练端查询由 `get_current_coach` 注入 coach_id 过滤，
越权/未分配资源统一 3001（不在出参里泄漏他人数据）。
"""

from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from .common import PageMeta
from .auth import UserBrief


class CoachLoginIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=6, max_length=128)


class CoachLoginData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    access_token: str  # admin 域 JWT（dom=admin, role=4）
    refresh_token: str


# ---- 工单（用户侧） ----


class CoachTicketIn(BaseModel):
    """提问/问诊：question 1-500 字；attach 为 JSONB 附件【假设】结构由前端自定。"""

    model_config = ConfigDict(from_attributes=True)

    question: str = Field(min_length=1, max_length=500)
    attach: Optional[dict[str, Any]] = None


class CoachTicketCreatedData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ticket_id: int
    status: int  # 1待回复
    created_at: datetime


class CoachTicketItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    coach_id: Optional[int] = None  # NULL=未分配
    title: Optional[str] = None
    status: int  # 1待回复 2已回复 3关闭
    created_at: datetime
    updated_at: datetime


class CoachTicketPageData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[CoachTicketItem]
    page: PageMeta


# ---- 工单消息 ----


class CoachMessageIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    content: str = Field(min_length=1, max_length=2000)


class CoachMessageData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    message_id: int


class CoachTicketMessageItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticket_id: int
    sender_role: int  # 1用户 2教练
    user_id: Optional[int] = None
    coach_id: Optional[int] = None
    content: str
    created_at: datetime


class CoachTicketDetailData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ticket: CoachTicketItem
    messages: list[CoachTicketMessageItem]


class CoachReplyData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    message_id: int
    status: int  # 回复后工单状态（2已回复）


# ---- 教练侧：被分配用户 ----


class CoachUserProfile(BaseModel):
    """用户档案摘要（教练只读最小集，避免暴露全部建档字段）。"""

    model_config = ConfigDict(from_attributes=True)

    gender: Optional[int] = None
    height_cm: Optional[float] = None
    current_weight: Optional[float] = None
    target_weight: Optional[float] = None
    target_calories: Optional[int] = None


class CoachUserRecordItem(BaseModel):
    """近期记录（日粒度快照摘要）。"""

    model_config = ConfigDict(from_attributes=True)

    date: date
    intake: Optional[float] = None
    deficit: Optional[float] = None
    steps: Optional[int] = None


class CoachAssignedUserItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user: UserBrief
    profile: Optional[CoachUserProfile] = None
    recent_records: list[CoachUserRecordItem] = Field(default_factory=list)


class CoachAssignedUserPageData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[CoachAssignedUserItem]
    page: PageMeta


# ---- 教练侧：被分配工单 ----


class CoachAssignedTicketListData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[CoachTicketItem]  # 仅本人被分配的工单（created_at DESC）
