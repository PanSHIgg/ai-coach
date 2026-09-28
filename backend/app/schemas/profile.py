"""身体档案域 schema（openapi: /api/body-profile，BodyProfileIn/BodyProfileOut）。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class BodyProfileIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    gender: int = Field(ge=1, le=2)  # 1男 2女
    # 校园边界（plan.md §7 QA）：身高 (0,200]、体重 (0,500]；越界 → 422/2001
    height_cm: float = Field(gt=0, le=200)
    # birth_year 写 SMALLINT：上界取 9999（未来年份由引擎回退默认 age），越界前置 422/2001
    birth_year: int | None = Field(default=None, ge=1900, le=9999)
    current_weight: float = Field(gt=0, le=500)  # kg
    target_weight: float | None = Field(default=None, gt=0, le=500)  # kg
    target_type: int = Field(ge=1, le=3)  # 1减脂 2增肌 3维持
    activity_level: int = Field(ge=1, le=5)  # 1卧床 2久坐 3轻度 4中度 5高度
    # goal_pace 写 SMALLINT：档位 0~3；越界前置 422/2001（避免写库溢出 500）
    goal_pace: int | None = Field(default=None, ge=0, le=3)


class BodyProfileOut(BodyProfileIn):
    """返回体在入参基础上追加 id 与服务端计算的 BMR/目标热量。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    bmr: float  # 基础代谢 kcal
    target_calories: int  # 每日热量预算 kcal
    created_at: datetime | None = None
    updated_at: datetime | None = None
