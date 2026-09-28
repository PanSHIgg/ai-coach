"""体重记录 schema。

【假设】P1 预留：openapi.yaml 已定义 WeightRecordIn/WeightRecordOut，
34 接口清单暂无对应端点；本文件按契约先行原则同步占位。
"""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class WeightRecordIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    weight: float  # kg
    record_at: Optional[date] = None
    source: Optional[int] = None  # 1手动 2智能秤
    note: Optional[str] = None


class WeightRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    weight: float
    record_at: date
    source: Optional[int] = None
    note: Optional[str] = None
    created_at: datetime
