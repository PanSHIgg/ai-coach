"""AI 域 schema（openapi: /api/ai/chat、/api/ai/times、/api/ai/recommend）。"""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class AiChatIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_id: str  # uuid
    message: str = Field(min_length=1)


class AiChatData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    reply: str
    intent: Optional[str] = None  # 如 hunger_rescue
    times_left: int
    references: list[str] = []  # 引用知识库条目 id


class AiTimesData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    times_left: int


class GeoLocation(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    lat: float
    lng: float


class AiRecommendIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    meal_type: int = Field(ge=1, le=4)  # 1早餐 2午餐 3晚餐 4加餐
    location: Optional[GeoLocation] = None
    budget: Optional[float] = None  # 预算上限（元）


class RecommendOption(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    food_id: Optional[int] = None
    name: str
    calories: float
    reason: str
    merchant_id: Optional[int] = None


class AiRecommendData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    options: list[RecommendOption]
