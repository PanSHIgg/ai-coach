"""热量账户域接口（openapi: /api/account/today、/api/account/trend）。"""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query

from app.api.deps import CurrentUser, get_current_user, get_request_id
from app.schemas import Envelope
from app.schemas.account import AccountTrendData, DailyAccount, DailyTrendItem, MealSummary
from app.schemas.common import ok

router = APIRouter(tags=["热量账户"])


@router.get("/account/today", response_model=Envelope[DailyAccount], summary="今日热量账户")
async def get_account_today(
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[DailyAccount]:
    # TODO(Phase1): 读 daily_snapshot（每日 0 点预生成）；P0 stub 对齐 mock
    data = DailyAccount(
        date=date.today(),
        bmr=1406,
        pal=1.4,
        neat=1644,
        eat=274,
        tef=150,
        tee=2392,
        intake=1418,
        deficit=-974,
        steps=12000,
        calories_burnt=320,
        calibration_used=True,
        meals=[MealSummary(meal_type=1, name="早餐", calories=380), MealSummary(meal_type=2, name="午餐", calories=620)],
    )
    return ok(data, request_id=request_id)


@router.get("/account/trend", response_model=Envelope[AccountTrendData], summary="账户趋势（按日）")
async def get_account_trend(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[AccountTrendData]:
    # TODO(Phase1): 按 start_date/end_date 查快照；【假设】缺省返回最近 7 天（契约注释）
    today = date.today()
    data = AccountTrendData(
        items=[
            DailyTrendItem(date=today - timedelta(days=1), intake=1900, tee=2392, deficit=-492, steps=10000, calories_burnt=300),
            DailyTrendItem(date=today, intake=1418, tee=2392, deficit=-974, steps=12000, calories_burnt=320),
        ]
    )
    return ok(data, request_id=request_id)
