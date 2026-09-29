"""订单域接口（openapi: /api/order、/{id}/pay、/notify、/{id}/redeem、/{id}/refund、/order/list）。

Phase 3 BE6：全部走 order_service 真实现（服务端重算金额 / 验签 / 幂等 / 核销留痕）。
Phase 5 F1：新增退款（2→5 幂等）；真实支付拉起参数由 wechat_pay 预下单产出。
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_current_user, get_request_id
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.schemas import Envelope
from app.schemas.common import PageMeta, ok
from app.schemas.order import (
    OrderBrief,
    OrderCreatedData,
    OrderCreateIn,
    OrderPageData,
    PayData,
    RedeemData,
    RedeemIn,
    RefundData,
    RefundIn,
)
from app.services import order_service

router = APIRouter(tags=["订单"])


@router.post("/order", response_model=Envelope[OrderCreatedData], summary="创建订单")
async def create_order(
    payload: OrderCreateIn,
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
    session: AsyncSession = Depends(get_db),
) -> Envelope[OrderCreatedData]:
    order = await order_service.create_order(session, user.id, payload)
    data = OrderCreatedData(
        order_id=order.id,
        order_no=order.order_no,
        total_amount=order.total_amount,
        discount_amount=order.discount_amount,
        pay_amount=order.pay_amount,  # 服务端重算，不信任前端
        expire_at=order.expire_at,
    )
    return ok(data, request_id=request_id)


@router.post("/order/{id}/pay", response_model=Envelope[PayData], summary="微信支付预下单")
async def pay_order(
    id: int,
    user: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    request_id: str | None = Depends(get_request_id),
    session: AsyncSession = Depends(get_db),
) -> Envelope[PayData]:
    """预下单：mock 模式直接推进支付成功并返回本地签名参数（含 mock 标记）；
    真实模式由 wechat_pay 预下单（未配置密钥时降级返回 degraded 占位参数）。

    订单状态推进统一由 service/notify 收敛，本接口只负责下发拉起参数。
    """
    order, pay_params = await order_service.pay_order(session, user.id, id, settings)
    data = PayData(order_id=order.id, status=order.status, pay_params=pay_params)
    return ok(data, request_id=request_id)


@router.post("/order/notify", response_model=Envelope[dict], summary="微信支付回调")
async def order_pay_notify(
    payload: dict = Body(default={}),
    request_id: str | None = Depends(get_request_id),
    session: AsyncSession = Depends(get_db),
) -> Envelope[dict]:
    """无认证（openapi security: []）；【假设】按内部 envelope 应答，协议转换在网关层。"""
    result = await order_service.handle_notify(session, payload)
    return ok(result, request_id=request_id)


@router.post("/order/{id}/redeem", response_model=Envelope[RedeemData], summary="核销")
async def redeem_order(
    id: int,
    payload: RedeemIn,
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
    session: AsyncSession = Depends(get_db),
) -> Envelope[RedeemData]:
    """商家侧核销（登录态仅作网关入口，归属以 body.merchant_id 校验）。"""
    await order_service.redeem_order(session, id, payload.redeem_code, payload.merchant_id, user.id)
    data = RedeemData(status="redeemed", redeemed_at=datetime.now(UTC))
    return ok(data, request_id=request_id)


@router.post("/order/{id}/refund", response_model=Envelope[RefundData], summary="申请退款")
async def refund_order(
    id: int,
    payload: RefundIn | None = Body(default=None),
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
    session: AsyncSession = Depends(get_db),
) -> Envelope[RefundData]:
    """退款：2 已支付待核销 → 5 已退款（幂等，重复申请返回成功）。

    不存在 3001 / 非本人 1002 / 状态不可退 2001；成功 refunded=true。
    """
    reason = payload.reason if payload is not None else None
    order = await order_service.refund_order(session, user.id, id, reason)
    data = RefundData(order_id=order.id, status=order.status, refunded=True)
    return ok(data, request_id=request_id)


@router.get("/order/list", response_model=Envelope[OrderPageData], summary="我的订单")
async def list_orders(
    status: int | None = Query(default=None, ge=1, le=5),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
    session: AsyncSession = Depends(get_db),
) -> Envelope[OrderPageData]:
    orders, total, merchant_names = await order_service.list_orders(
        session, user.id, status, page, page_size
    )
    items = []
    for o in orders:
        brief = OrderBrief.model_validate(o)
        brief.merchant_name = merchant_names.get(o.merchant_id or 0)
        items.append(brief)
    data = OrderPageData(items=items, page=PageMeta(page=page, page_size=page_size, total=total))
    return ok(data, request_id=request_id)
