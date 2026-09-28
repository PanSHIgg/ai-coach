"""运营看板 schema（openapi: /api/admin/dashboard）。"""

from datetime import date

from pydantic import BaseModel, ConfigDict


class DashboardData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    date: date
    user_count: int
    active_users_today: int
    meal_records_today: int
    orders_today: int
    gmv_today: float  # 元
    ai_calls_today: int
