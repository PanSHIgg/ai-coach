"""体重记录 schema（openapi: /api/weight*，BE-w）。

Phase 1 新增端点（openapi.yaml 同步补充）：GET /api/weight/list、POST /api/weight、
DELETE /api/weight/{id}、GET /api/weight/trend。
"""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .common import PageMeta


class WeightRecordIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    weight: float = Field(gt=0, le=500)  # kg
    record_at: Optional[date] = None
    # source 写 SMALLINT：1手动 2智能秤；越界前置 422/2001（避免写库溢出 500）
    source: Optional[int] = Field(default=None, ge=1, le=2)
    note: Optional[str] = None


class WeightRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    weight: float
    record_at: date
    source: Optional[int] = None
    note: Optional[str] = None
    created_at: datetime


class WeightPageData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[WeightRecordOut]
    page: PageMeta


class WeightDeleteData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    deleted: bool = True


class WeightTrendItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    date: date
    weight: float


class WeightTrendData(BaseModel):
    """体重趋势：按 record_at 升序的折线数据点。"""

    model_config = ConfigDict(from_attributes=True)

    items: list[WeightTrendItem]
    start_weight: Optional[float] = None
    latest_weight: Optional[float] = None
    change: Optional[float] = None  # latest - start（kg，正为增重）
