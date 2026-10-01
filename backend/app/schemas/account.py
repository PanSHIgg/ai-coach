"""热量账户域 schema（openapi: /api/account/*，DailyAccount/MealSummary/趋势）。"""

from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class TodayStatusIn(BaseModel):
    """POST /api/account/today-status 入参：当日所选状态（§2.3.1 五选一）。"""

    model_config = ConfigDict(from_attributes=True)

    activity_level: int = Field(ge=1, le=5)  # 1卧床 2久坐 3轻度 4中度 5高度


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
    today_left: float = 0  # 环形图「还能吃」= BMR×PAL − 摄入 + 运动 − TEF（M1 对拍口径）
    # 当日已选状态（1~5）；null=未选，前端据此判断是否弹「今天什么状态」（F-01）
    activity_level: Optional[int] = None
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
