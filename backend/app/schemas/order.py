"""订单域 schema（openapi: /api/order*）。"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from .common import PageMeta


class OrderItemIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sku_id: int
    qty: int = Field(ge=1)


class OrderCreateIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    merchant_id: int
    items: list[OrderItemIn] = Field(min_length=1)
    coupon_id: Optional[int] = None


class OrderCreatedData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    order_id: int
    order_no: str
    total_amount: float
    discount_amount: float
    pay_amount: float  # 服务端重算，不信任前端
    expire_at: datetime  # 支付截止时间


class PayData(BaseModel):
    """【假设】透传微信小程序拉起支付所需参数。"""

    model_config = ConfigDict(from_attributes=True)

    order_id: int
    status: int  # 1待支付 2已支付待核销 3已完成 4已取消 5已退款
    pay_params: dict[str, Any]  # timeStamp/nonceStr/package/paySign


class RedeemIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    redeem_code: str
    merchant_id: int


class RedeemData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: str  # "redeemed"
    redeemed_at: datetime


class OrderBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_no: str
    merchant_id: int
    merchant_name: Optional[str] = None
    total_amount: float
    discount_amount: float
    pay_amount: float
    status: int  # 1待支付 2已支付待核销 3已完成 4已取消 5已退款
    redeem_code: Optional[str] = None
    expire_at: Optional[datetime] = None
    created_at: datetime


class OrderPageData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[OrderBrief]
    page: PageMeta


class RefundIn(BaseModel):
    """退款申请（可选原因，最长 128）。"""

    model_config = ConfigDict(from_attributes=True)

    reason: Optional[str] = Field(default=None, max_length=128)


class RefundData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    order_id: int
    status: int  # 5已退款
    refunded: bool
