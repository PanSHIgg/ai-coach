"""任务中心 / 每日签到 / 积分 schema（openapi: /api/task/*、/api/points、/api/points/list）。

【假设】积分口径（签到/任务奖励分值、连续签到递增、兑换门槛）文档未给，
具体数值由 task_service 与运营配置决定；本文件只固化与契约一致的字段结构。
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from .common import PageMeta


class TaskItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str  # daily_checkin / complete_profile / first_ai_check 等
    name: str
    reward_points: int
    reward_desc: Optional[str] = None
    status: int  # 0未完成 1已完成/已领取
    progress: int = 0  # 进度（0-100 百分比或步数）


class TaskListData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[TaskItem]


class TaskCheckinData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    points_added: int  # 当日重复签到为 0
    total_points: int
    streak: int  # 连续签到天数


class PointsThreshold(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    points: int
    reward_desc: str


class PointsOverviewData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    balance: int
    total_earned: int
    thresholds: list[PointsThreshold]


class PointsRecordItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    change: int  # 正=获得 负=消耗
    reason: str
    created_at: datetime


class PointsPageData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[PointsRecordItem]
    page: PageMeta