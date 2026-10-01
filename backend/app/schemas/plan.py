"""平台自营会员订阅域 schema（openapi: /api/plan/*，current.md §2.1 G2）。

路径族刻意避开 `/api/subscription`（已被「提醒订阅」占用）与 `/api/order`
（order 绑定 merchant_id 与核销语义，平台自营无商家）。
金额一律服务端按 tier 重算（PlanOrderIn 只收 tier，不收金额）。
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .common import PageMeta


class PlanTierItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tier: int  # 1进阶 2高级 3终身
    name: str
    price: float  # 元（2 位小数）
    valid_days: Optional[int] = None  # NULL=终身不限期；30=包月 30 天
    ai_times: int  # 购买后 AI 次数额度
    coach_times: int  # 购买后真人教练次数额度
    description: Optional[str] = None


class PlanListData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[PlanTierItem]


class PlanBenefitData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tier: int  # 0基础 1进阶 2高级 3终身
    ai_times_left: int
    coach_times_left: int
    valid_to: Optional[datetime] = None  # NULL=不限期/基础档
    expired: bool  # valid_to 已过期（权益降级判定由业务层处理）


class PlanOrderIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tier: int = Field(ge=1, le=3)  # 金额服务端重算，不信任前端


class PlanOrderData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    order_id: int
    order_no: str
    tier: int
    pay_amount: float  # 服务端重算
    expire_at: datetime  # 15 分钟后过期


class PlanPayData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    order_id: int
    status: int  # 1待支付 2已支付 3已取消
    pay_params: dict  # 微信小程序拉起支付参数；PAY_MOCK_MODE 下为空对象


class PlanNotifyIn(BaseModel):
    """支付回调入参：签名 = HMAC-SHA256(JWT_SECRET, f"{order_no}|{amount:.2f}")。

    与 `/api/order/notify` 复用 `order_service.notify_sign` 的同一套签名口径，
    避免两套支付回调签名漂移。
    """

    model_config = ConfigDict(from_attributes=True)

    order_no: str
    amount: float
    sign: str


class PlanNotifyData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    result: str  # "ok"（幂等：重复回调仍返回 ok）


class PlanOrderItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_no: str
    tier: int
    pay_amount: float
    status: int  # 1待支付 2已支付 3已取消
    expire_at: Optional[datetime] = None
    paid_at: Optional[datetime] = None
    created_at: datetime


class PlanOrderPageData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[PlanOrderItem]
    page: PageMeta
