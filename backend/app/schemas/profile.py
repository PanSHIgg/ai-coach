"""身体档案域 schema（openapi: /api/body-profile，BodyProfileIn/BodyProfileOut）。"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class BodyProfileIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    gender: int = Field(ge=1, le=2)  # 1男 2女
    height_cm: float
    birth_year: Optional[int] = None
    current_weight: float  # kg
    target_weight: Optional[float] = None  # kg
    target_type: int = Field(ge=1, le=3)  # 1减脂 2增肌 3维持
    activity_level: int = Field(ge=1, le=5)  # 1卧床 2久坐 3轻度 4中度 5高度
    goal_pace: Optional[int] = None  # 每周目标 kg 档位；【假设】缺省 1（每周 0.5kg）


class BodyProfileOut(BodyProfileIn):
    """返回体在入参基础上追加 id 与服务端计算的 BMR/目标热量。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    bmr: float  # 基础代谢 kcal
    target_calories: int  # 每日热量预算 kcal
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
