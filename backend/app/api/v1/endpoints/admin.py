"""管理域接口（openapi: /api/admin/dashboard）。"""

from datetime import date

from fastapi import APIRouter, Depends, Query

from app.api.deps import CurrentUser, get_current_user, get_request_id
from app.schemas import DashboardData, Envelope
from app.schemas.common import ok

router = APIRouter(tags=["管理"])


@router.get("/admin/dashboard", response_model=Envelope[DashboardData], summary="运营看板")
async def get_admin_dashboard(
    date: date | None = Query(default=None),
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[DashboardData]:
    # TODO(Phase1): 运营侧聚合统计；权限校验 admin_user.role（1002 无权限）
    data = DashboardData(
        date=date or date.today(),
        user_count=1200,
        active_users_today=356,
        meal_records_today=980,
        orders_today=120,
        gmv_today=3360.0,
        ai_calls_today=2100,
    )
    return ok(data, request_id=request_id)
