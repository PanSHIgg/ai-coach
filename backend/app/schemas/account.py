"""热量账户域 schema（openapi: /api/account/*，DailyAccount/MealSummary/趋势）。"""

from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict


class MealSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    meal_type: int  # 1早餐 2午餐 3晚餐 4加餐
    name: str
    calories: float


class DailyAccount(BaseModel):
    """GET /api/account/today → data（05 文档 §8.4.4 示例字段）。"""

    model_config = ConfigDict(from_attributes=True)

    date: date
    bmr: float
    pal: float
    neat: float
    eat: Optional[float] = None
    tef: float
    tee: float
    intake: float  # 今日摄入 kcal
    deficit: float  # 负值为热量缺口
    steps: int
    calories_burnt: float = 0  # 运动消耗 kcal
    calibration_used: bool = False
    meals: list[MealSummary] = []


class DailyTrendItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    date: date
    intake: float
    tee: float
    deficit: float
    steps: int = 0
    calories_burnt: float = 0


class AccountTrendData(BaseModel):
    """GET /api/account/trend → data；【假设】缺省返回最近 7 天。"""

    model_config = ConfigDict(from_attributes=True)

    items: list[DailyTrendItem]
