"""记录域 schema（openapi: /api/food/search、/api/meal/*、/api/sport*、/api/steps/sync）。"""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
    protein_100g: float | None = None
    fat_100g: float | None = None
    carb_100g: float | None = None
    gi: float | None = None  # 血糖生成指数


class FoodSearchData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[FoodItem]
    total: int


# ---- 用户自定义食物（F-02）----


class FoodCustomIn(BaseModel):
    """新建自定义食物入参（名称必填，热量等数值合理）。"""

    model_config = ConfigDict(from_attributes=True)

    name: str = Field(min_length=1, max_length=128)
    calories_100g: float = Field(gt=0, le=1000)  # 每 100g 热量 kcal（食用油约 900 为上限）
    protein_100g: float | None = Field(default=None, ge=0, le=100)
    fat_100g: float | None = Field(default=None, ge=0, le=100)
    carb_100g: float | None = Field(default=None, ge=0, le=100)

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        """名称去空白后不得为空（防「   」绕过 min_length）。"""
        stripped = value.strip()
        if not stripped:
            raise ValueError("食物名称不能为空")
        return stripped


class FoodCustomData(BaseModel):
    """新建自定义食物返回（audit_status 恒为 0 待审，仅本人可见）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    calories_100g: float
    audit_status: int


# ---- 拍照识别 ----


class MatchCandidate(BaseModel):
    """识别响应里的召回候选（契约组件名逐字对齐 openapi.yaml 与两份 TS 副本）。"""

    model_config = ConfigDict(from_attributes=True)

    food_id: int
    name: str
    calories_100g: float
    score: float


class RecognizedItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    # 未匹配到 food 表时为 None（契约 nullable），此时 need_confirm 必为 True
    food_id: int | None = None
    name: str
    confidence: float  # <0.7 需用户确认
    amount_g: float
    calories: float
    # ambiguous=True 且 food_id=None：召回到候选但不确定，应让用户从 candidates 里选；
    # ambiguous=False 且 food_id=None：库里确实没有（§2.4 回落手动录入/自定义食物）
    ambiguous: bool = False
    candidates: list[MatchCandidate] = []


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
    amount_g: float = Field(gt=0, le=10000)  # 上界防 DB 溢出（>10000g → 422/2001）
    source: int = Field(ge=1, le=4)  # 1拍照 2语音 3手动 4AI推荐
    image_url: str | None = None


class MealUpdateIn(BaseModel):
    """部分更新；至少提供一个字段（路由层校验）。"""

    model_config = ConfigDict(from_attributes=True)

    meal_type: int | None = Field(default=None, ge=1, le=4)
    food_id: int | None = None
    amount_g: float | None = Field(default=None, gt=0, le=10000)
    source: int | None = Field(default=None, ge=1, le=4)
    image_url: str | None = None


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
    food_id: int | None = None
    food_name: str  # 快照，防食物库变更
    amount_g: float
    calories: float
    protein: float | None = None
    fat: float | None = None
    carb: float | None = None
    confidence: float | None = None
    source: int
    image_url: str | None = None
    record_date: date
    created_at: datetime


class MealPageData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[MealRecordOut]
    page: PageMeta


# ---- 运动记录 ----


class SportIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    # sport_name 写 VARCHAR(128)：超长前置 422/2001（避免写库溢出 500）
    sport_name: str | None = Field(default=None, max_length=128)
    met: float | None = Field(default=None, gt=0, le=25)  # 不传按 sport_name 映射标准表
    duration_min: int = Field(ge=1, le=1440)  # 上界 24h，防 DB 溢出 → 422/2001
    record_at: datetime | None = None


class SportCreatedData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    calories: float
    today_burnt: float = 0  # 今日运动总消耗 kcal


class SportRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sport_name: str | None = None
    met: float | None = None
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
    steps: int = Field(ge=0, le=200000)  # 上界防 DB 溢出 → 422/2001
    hourly: dict[str, int] | None = None  # 键为 0-23 小时、值为非负整数步数
    # 微信运动加密数据（uni.getWeRunData）：两者成对出现，后端用**该用户本次登录**的
    # session_key 解密；缺任一或解密/校验失败 → 明确降级按 steps 计（不伪造，见 steps_source）
    encrypted_data: str | None = None
    iv: str | None = None

    @field_validator("hourly")
    @classmethod
    def _check_hourly_steps(cls, value: dict[str, int] | None) -> dict[str, int] | None:
        """小时键须为 0-23；值为非负整数且 ≤ 200000，越界/非法 → 422/2001。"""
        if value:
            for key, steps in value.items():
                try:
                    hour = int(key)
                except (TypeError, ValueError) as exc:
                    raise ValueError("hourly 键应为 0-23 的小时") from exc
                if hour < 0 or hour > 23:
                    raise ValueError("hourly 键应为 0-23 的小时")
                if steps is None or steps < 0:
                    raise ValueError("单小时步数不能为负")
                if steps > 200000:
                    raise ValueError("单小时步数超出合理范围")
        return value


class StepsSyncData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    neat_calibrated: float
    met: float
    delta_calories: float
    steps: int  # 实际入库步数；目标日期无微信记录时不得借用其它日期顶替
    steps_source: int  # 1=微信运动解密成功 2=客户端传入值 3=未取到，按 PAL 估算
    # 本次顺带回填的历史天数（不含当天）；仅 steps_source=1 可能 >0，降级路径恒 0
    backfilled_days: int = 0


class StepTrendItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    date: date
    steps: int
    source: int  # 1=微信运动解密回填 2=客户端传入/手动


class StepsTrendData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    # 按日期升序；无记录的日期不出现（不补零，避免把"没同步过"画成"走了 0 步"）
    items: list[StepTrendItem]
