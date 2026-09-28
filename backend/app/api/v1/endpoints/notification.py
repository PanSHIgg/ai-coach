"""提醒订阅接口（BE-n 归属本模块）。

GET /api/subscription、POST /api/subscription、POST /api/subscription/cancel。
订阅设置走真实实现（幂等 upsert / 取消）；调度入口见 notification_service.enqueue_due_reminders。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_current_user, get_request_id
from app.db.session import get_db
from app.schemas import Envelope
from app.schemas.common import ok
from app.schemas.notification import SubscriptionData, SubscriptionIn, SubscriptionOut
from app.services import notification_service

router = APIRouter(tags=["订阅"])


@router.get("/subscription", response_model=Envelope[SubscriptionData], summary="我的订阅设置")
async def list_subscriptions(
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
    session: AsyncSession = Depends(get_db),
) -> Envelope[SubscriptionData]:
    data = await notification_service.list_subscriptions(session, user.id)
    return ok(data, request_id=request_id)


@router.post("/subscription", response_model=Envelope[SubscriptionOut], summary="订阅提醒")
async def subscribe(
    payload: SubscriptionIn,
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
    session: AsyncSession = Depends(get_db),
) -> Envelope[SubscriptionOut]:
    data = await notification_service.subscribe(session, user.id, payload.template_type)
    return ok(data, request_id=request_id)


@router.post("/subscription/cancel", response_model=Envelope[SubscriptionOut], summary="取消订阅")
async def cancel_subscription(
    payload: SubscriptionIn,
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
    session: AsyncSession = Depends(get_db),
) -> Envelope[SubscriptionOut]:
    data = await notification_service.cancel_subscription(session, user.id, payload.template_type)
    return ok(data, request_id=request_id)
