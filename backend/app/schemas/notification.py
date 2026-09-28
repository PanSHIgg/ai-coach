"""提醒订阅 schema（BE-n）。

Phase 1 新增端点（openapi.yaml 同步补充）：GET /api/subscription、POST /api/subscription、
POST /api/subscription/cancel。

template_type：1午餐提醒 2晚餐提醒 3深夜防崩塌 4称重提醒（默认定时任务：餐前 11:00/17:00）。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SubscriptionIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    template_type: int = Field(ge=1, le=4)


class SubscriptionItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    template_type: int
    status: int  # 1已订阅 0已退订
    subscribe_count: int = 0
    last_subscribe_at: datetime | None = None


class SubscriptionData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[SubscriptionItem]


class SubscriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    template_type: int
    status: int
    subscribe_count: int = 0
    last_subscribe_at: datetime | None = None
