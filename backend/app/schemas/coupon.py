"""券域 schema（openapi: /api/coupon/list）。"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from .common import PageMeta


class CouponOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    type: int  # 1满减 2折扣 3免费 4体验
    scope: int  # 1吃 2动 3异业 4通用
    amount: float  # 减免金额（元），折扣券为 0
    discount_rate: Optional[float] = None
    min_spend: float = 0  # 门槛金额（元）
    merchant_id: Optional[int] = None
    status: int  # 1未用 2已用 3过期 4作废
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    # status=2 需靠这两个字段区分「下单锁定」与「真已消费」：
    # order_id 非空且 used_at 为空 = 被订单占用、尚可取消回滚；used_at 非空 = 已核销/已消费。
    used_at: Optional[datetime] = None
    order_id: Optional[int] = None


class CouponPageData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[CouponOut]
    page: PageMeta
