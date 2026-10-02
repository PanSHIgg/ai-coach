"""热量账户域接口（openapi: /api/account/today、/api/account/trend）。"""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_current_user, get_request_id
from app.db.session import get_db
from app.schemas import Envelope
from app.schemas.account import AccountTrendData, DailyAccount, TodayStatusIn
from app.schemas.common import ok
from app.services import account as account_service

router = APIRouter(tags=["热量账户"])


@router.get("/account/today", response_model=Envelope[DailyAccount], summary="今日热量账户")
async def get_account_today(
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
    session: AsyncSession = Depends(get_db),
) -> Envelope[DailyAccount]:
    # 先确保当日快照最新（幂等重算），再返回账户；未建档由 account 服务抛 3001。
    data = await account_service.get_today(session, user.id)
    return ok(data, request_id=request_id)


@router.post(
    "/account/today-status",
    response_model=Envelope[DailyAccount],
    summary="写入当日状态（卧床/久坐/轻度/中度/高度五选一）",
)
async def set_account_today_status(
    payload: TodayStatusIn,
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
    session: AsyncSession = Depends(get_db),
) -> Envelope[DailyAccount]:
    # 当日状态写入 daily_snapshot.activity_level，当日 PAL/NEAT 即时按该状态取值；
    # 未选回退建档 activity_level（§2.3.1「不点则用默认 PAL」）。未建档抛 3001。
    data = await account_service.set_today_status(session, user.id, payload.activity_level)
    return ok(data, request_id=request_id)


@router.get("/account/trend", response_model=Envelope[AccountTrendData], summary="账户趋势（按日）")
async def get_account_trend(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
    session: AsyncSession = Depends(get_db),
) -> Envelope[AccountTrendData]:
    # 按 start_date/end_date 查快照；【假设】缺省返回最近 7 天（契约注释）。
    data = await account_service.get_trend(session, user.id, start_date, end_date)
    return ok(data, request_id=request_id)


@router.delete("/account", response_model=Envelope[dict], summary="账号注销（级联清除）")
async def delete_account(
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
    session: AsyncSession = Depends(get_db),
) -> Envelope[dict]:
    # 单事务内按外键依赖序级联清除用户全部关联数据，最后删 "user" 行（G7 / 04 §6.3）。
    # 未登录或用户已注销（token 指向已删用户）→ get_current_user 统一 1001/401。
    await account_service.delete_account(session, user.id)
    return ok({"deleted": True}, request_id=request_id)
