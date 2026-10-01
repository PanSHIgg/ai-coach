"""身体档案域 schema（openapi: /api/body-profile，BodyProfileIn/BodyProfileOut）。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class BodyProfileIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    gender: int = Field(ge=1, le=2)  # 1男 2女
    # 校园边界（plan.md §7 QA）：身高 (0,200]、体重 (0,500]；越界 → 422/2001
    height_cm: float = Field(gt=0, le=200)
    # IS-005: birth_year 静态边界 1900-9999（与契约 openapi.yaml 对齐）
    # 动态年龄校验见 _validate_birth_year
    birth_year: int | None = Field(default=None, ge=1900, le=9999)
    current_weight: float = Field(gt=0, le=500)  # kg
    target_weight: float | None = Field(default=None, gt=0, le=500)  # kg
    # 文档 §13.3：未填默认 1（减脂，每周 0.5kg）；越界仍 422/2001
    target_type: int = Field(default=1, ge=1, le=3)  # 1减脂 2增肌 3维持
    # 文档 §13.3：未填默认 2（久坐，PAL 1.4）；越界仍 422/2001
    activity_level: int = Field(default=2, ge=1, le=5)  # 1卧床 2久坐 3轻度 4中度 5高度
    # goal_pace 写 SMALLINT：档位 0~3；越界前置 422/2001（避免写库溢出 500）
    goal_pace: int | None = Field(default=None, ge=0, le=3)

    @field_validator("birth_year")
    @classmethod
    def _validate_birth_year(cls, v: int | None) -> int | None:
        """IS-005: 按当前年份动态校验 age ∈ [10, 120]。"""
        if v is None:
            return v
        current_year = datetime.now().year
        min_year = current_year - 120
        max_year = current_year - 10
        if not (min_year <= v <= max_year):
            raise ValueError(
                f"birth_year 必须在 {min_year}-{max_year} 之间（对应年龄 10-120 岁）"
            )
        return v


class BodyProfileOut(BodyProfileIn):
    """返回体在入参基础上追加 id 与服务端计算的 BMR/目标热量。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    bmr: float  # 基础代谢 kcal
    target_calories: int  # 每日热量预算 kcal
    created_at: datetime | None = None
    updated_at: datetime | None = None
