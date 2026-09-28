"""记录域 schema（openapi: /api/food/search、/api/meal/*、/api/sport*、/api/steps/sync）。"""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .common import PageMeta


# ---- 食物搜索 ----

class FoodSearchIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    keyword: str = Field(min_length=1)
    limit: int = Field(default=20, ge=1, le=100)


class FoodItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    calories_100g: float  # 每 100g 热量 kcal
    protein_100g: Optional[float] = None
    fat_100g: Optional[float] = None
    carb_100g: Optional[float] = None
    gi: Optional[float] = None  # 血糖生成指数


class FoodSearchData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[FoodItem]
    total: int


# ---- 拍照识别 ----

class RecognizedItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    food_id: int
    name: str
    confidence: float  # <0.7 需用户确认
    amount_g: float
    calories: float


class RecognizeData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    request_id: str
    items: list[RecognizedItem]
    need_confirm: bool


# ---- 饮食记录 ----

class MealCreateIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    meal_type: int = Field(ge=1, le=4)  # 1早餐 2午餐 3晚餐 4加餐
    food_id: int
    amount_g: float = Field(gt=0)
    source: int = Field(ge=1, le=4)  # 1拍照 2语音 3手动 4AI推荐
    image_url: Optional[str] = None


class MealUpdateIn(BaseModel):
    """部分更新；至少提供一个字段（路由层校验）。"""

    model_config = ConfigDict(from_attributes=True)

    meal_type: Optional[int] = Field(default=None, ge=1, le=4)
    food_id: Optional[int] = None
    amount_g: Optional[float] = Field(default=None, gt=0)
    source: Optional[int] = Field(default=None, ge=1, le=4)
    image_url: Optional[str] = None


class MealCreatedData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    calories: float
    today_intake: float  # 重算后的今日摄入 kcal
    today_left: float  # 今日剩余额度 kcal


class MealDeleteData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    deleted: bool = True


class MealRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    meal_type: int
    food_id: Optional[int] = None
    food_name: str  # 快照，防食物库变更
    amount_g: float
    calories: float
    protein: Optional[float] = None
    fat: Optional[float] = None
    carb: Optional[float] = None
    confidence: Optional[float] = None
    source: int
    image_url: Optional[str] = None
    record_date: date
    created_at: datetime


class MealPageData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[MealRecordOut]
    page: PageMeta


# ---- 运动记录 ----

class SportIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sport_name: Optional[str] = None
    met: Optional[float] = None  # 不传按 sport_name 映射标准表
    duration_min: int = Field(ge=1)
    record_at: Optional[datetime] = None


class SportCreatedData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    calories: float
    today_burnt: float = 0  # 今日运动总消耗 kcal


class SportRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sport_name: Optional[str] = None
    met: Optional[float] = None
    duration_min: int
    calories: float
    record_at: datetime
    created_at: datetime


class SportPageData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[SportRecordOut]
    page: PageMeta


# ---- 步数同步（NEAT 校准）----

class StepsSyncIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    date: date
    steps: int = Field(ge=0)
    hourly: Optional[dict[str, int]] = None  # 键为 0-23 小时


class StepsSyncData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    neat_calibrated: float
    met: float
    delta_calories: float
