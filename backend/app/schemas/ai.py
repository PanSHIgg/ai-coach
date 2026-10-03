"""AI 域 schema（openapi: /api/ai/chat、/api/ai/times、/api/ai/recommend）。"""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AiChatIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_id: str  # uuid
    # 上界防超长提示词打爆 LLM 费用/超时（>500 字 → 422/2001）；
    # 支持纯图片消息：message 为空时必须带 image_url（文字与图片至少一项）
    message: str = Field(default="", max_length=500)
    # 随对话上传的图片 URL（前端 COS 直传后的公开读地址，scene=chat）
    image_url: Optional[str] = Field(default=None, max_length=512)

    @model_validator(mode="after")
    def _require_message_or_image(self) -> "AiChatIn":
        if not (self.message.strip() or self.image_url):
            raise ValueError("message 与 image_url 至少一项")
        return self


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


# ---- Phase 4 BE7c：AI 周点评 ----

class WeeklyCommentIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    week: Optional[str] = Field(default=None, max_length=16)  # 期号 YYYY-Www；缺省=本周


class WeeklyCommentData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    week: str  # 期号 YYYY-Www
    content: str  # AI 周点评（含免责声明）
    highlights: list[str] = []  # 关键指标要点
    references: list[str] = []  # 引用知识库条目 id
