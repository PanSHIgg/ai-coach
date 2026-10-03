"""平台自营会员订阅付费接口（openapi: /api/plan/*）。

**路径族刻意避开 `/api/subscription`（已被「提醒订阅」占用）与 `/api/order`**
（order 绑定 merchant_id 与核销语义，平台自营无商家），故新建 plan_order 表。

本文件只做**协议层**：参数校验 + schema 组装；业务逻辑全在 `app/services/plan_service.py`
（服务端重算金额、下单/支付/回调验签幂等、权益发放、到期降级）。

【假设】终身档价格与权益额度文档未给，集中在 `plan_service.PLAN_TIERS` 常量中，
后续改为运营可配时只需调整此处（服务端重算金额的唯一来源）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_request_id
from app.db.session import get_db
from app.schemas import Envelope
from app.schemas.common import PageMeta, ok
from app.schemas.plan import (
    PlanBenefitData,
    PlanListData,
    PlanNotifyData,
    PlanNotifyIn,
    PlanOrderData,
    PlanOrderIn,
    PlanOrderItem,
    PlanOrderPageData,
    PlanPayData,
    PlanTierItem,
)
from app.services import plan_service

router = APIRouter(tags=["会员套餐"])


# 套餐与权益


@router.get("/plan/list", response_model=Envelope[PlanListData], summary="会员档位与价格")
async def list_plans(
    user=Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[PlanListData]:
    return ok(
        PlanListData(
            items=[
                PlanTierItem(
                    tier=int(c["tier"]),
                    name=str(c["name"]),
                    price=float(c["price"]),
                    valid_days=c["valid_days"],
                    ai_times=int(c["ai_times"]),
                    coach_times=int(c["coach_times"]),
                    description=c["description"],
                )
                for c in plan_service.list_tiers()
            ]
        ),
        request_id=request_id,
    )


@router.get("/plan/benefit", response_model=Envelope[PlanBenefitData], summary="当前用户会员权益")
async def get_plan_benefit(
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[PlanBenefitData]:
    return ok(
        PlanBenefitData(**(await plan_service.get_benefit(session, user.id))),
        request_id=request_id,
    )


# 下单 / 支付 / 回调 / 订单列表


@router.post("/plan/order", response_model=Envelope[PlanOrderData], summary="创建会员订阅订单")
async def create_plan_order(
    payload: PlanOrderIn,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[PlanOrderData]:
    order = await plan_service.create_order(session, user.id, payload.tier)
    return ok(
        PlanOrderData(
            order_id=order.id,
            order_no=order.order_no,
            tier=order.tier,
            pay_amount=order.pay_amount,
            expire_at=order.expire_at,
        ),
        request_id=request_id,
    )


@router.post("/plan/order/{id}/pay", response_model=Envelope[PlanPayData], summary="会员订单支付")
async def pay_plan_order(
    id: int,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[PlanPayData]:
    order, pay_params = await plan_service.pay_order(session, user.id, id)
    return ok(
        PlanPayData(order_id=order.id, status=order.status, pay_params=pay_params),
        request_id=request_id,
    )


@router.post(
    "/plan/notify", response_model=Envelope[PlanNotifyData], summary="会员支付回调（验签+幂等）"
)
async def plan_pay_notify(
    payload: PlanNotifyIn,
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[PlanNotifyData]:
    return ok(
        PlanNotifyData(**(await plan_service.handle_notify(session, payload))),
        request_id=request_id,
    )


@router.get("/plan/orders", response_model=Envelope[PlanOrderPageData], summary="我的会员订单")
async def list_plan_orders(
    status: int | None = Query(default=None, ge=1, le=3),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[PlanOrderPageData]:
    rows, total = await plan_service.list_orders(session, user.id, status, page, page_size)
    return ok(
        PlanOrderPageData(
            items=[PlanOrderItem.model_validate(r) for r in rows],
            page=PageMeta(page=page, page_size=page_size, total=total),
        ),
        request_id=request_id,
    )
