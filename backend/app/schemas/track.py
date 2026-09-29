"""埋点上报 schema（openapi: /api/track，F3）。

契约真源：`contracts/openapi.yaml` 的 TrackEventIn / TrackIn / TrackData。
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class TrackEventIn(BaseModel):
    """单个埋点事件。未带 occurred_at 时以服务端 NOW() 落库。"""

    model_config = ConfigDict(from_attributes=True)

    event: str = Field(min_length=1, max_length=64)
    properties: dict[str, Any] = Field(default_factory=dict)
    occurred_at: Optional[datetime] = None


class TrackIn(BaseModel):
    """批量上报（一次最多 50 条，避免单请求写放大）。"""

    model_config = ConfigDict(from_attributes=True)

    events: list[TrackEventIn] = Field(min_length=1, max_length=50)
    device_id: Optional[str] = Field(default=None, max_length=64)
    platform: int = Field(default=1, ge=1, le=3)  # 1小程序 2H5 3admin后台


class TrackData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    accepted: int
