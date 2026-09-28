"""订单域接口（openapi: /api/order、/api/order/{id}/pay、/api/order/notify、/api/order/{id}/redeem、/api/order/list）。"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Body, Depends, Query

from app.api.deps import CurrentUser, get_current_user, get_request_id
from app.schemas import Envelope
from app.schemas.common import PageMeta, ok
from app.schemas.order import (
    OrderBrief,
    OrderCreateIn,
    OrderCreatedData,
    OrderPageData,
    PayData,
    RedeemData,
    RedeemIn,
)

router = APIRouter(tags=["订单"])


@router.post("/order", response_model=Envelope[OrderCreatedData], summary="创建订单")
async def create_order(
    payload: OrderCreateIn,
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[OrderCreatedData]:
    # TODO(Phase1): 服务端重算金额（不信任前端）+ 券校验（5002）+ 商家状态（5001）
    data = OrderCreatedData(
        order_id=66001,
        order_no="DD202609280001",
        total_amount=28.0,
        discount_amount=3.0,
        pay_amount=25.0,
        expire_at=datetime.now() + timedelta(minutes=15),
    )
    return ok(data, request_id=request_id)


@router.post("/order/{id}/pay", response_model=Envelope[PayData], summary="微信支付预下单")
async def pay_order(
    id: int,
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[PayData]:
    # TODO(Phase1): 微信支付统一下单（W11 联调）；订单超时返回 5003
    data = PayData(
        order_id=id,
        status=1,
        pay_params={
            "timeStamp": "1790000000",
            "nonceStr": "mock",
            "package": "prepay_id=mock",
            "paySign": "mock",
        },
    )
    return ok(data, request_id=request_id)


@router.post("/order/notify", response_model=Envelope[dict], summary="微信支付回调")
async def order_pay_notify(
    payload: dict = Body(default={}),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[dict]:
    """无认证（openapi security: []）；【假设】按内部 envelope 应答，协议转换在网关层。"""
    # TODO(Phase1): 验签 + 订单状态机推进（1待支付 → 2已支付待核销）
    return ok({"result": "ok"}, request_id=request_id)


@router.post("/order/{id}/redeem", response_model=Envelope[RedeemData], summary="核销")
async def redeem_order(
    id: int,
    payload: RedeemIn,
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[RedeemData]:
    # TODO(Phase1): 核销码唯一校验（5004 已使用）+ 归属商家校验 + 释放库存
    data = RedeemData(status="redeemed", redeemed_at=datetime.now())
    return ok(data, request_id=request_id)


@router.get("/order/list", response_model=Envelope[OrderPageData], summary="我的订单")
async def list_orders(
    status: int | None = Query(default=None, ge=1, le=5),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[OrderPageData]:
    # TODO(Phase1): order 表分页（user_id 行级隔离，created_at DESC）
    data = OrderPageData(
        items=[
            OrderBrief(
                id=66001,
                order_no="DD202609280001",
                merchant_id=88,
                merchant_name="轻食一号店",
                total_amount=28.0,
                discount_amount=3.0,
                pay_amount=25.0,
                status=2,
                redeem_code="RD-ABC123",
                expire_at=datetime.now() + timedelta(minutes=15),
                created_at=datetime.now(),
            )
        ],
        page=PageMeta(page=page, page_size=page_size, total=1),
    )
    return ok(data, request_id=request_id)
