"""券域接口（openapi: /api/coupon/list）。"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query

from app.api.deps import CurrentUser, get_current_user, get_request_id
from app.schemas import Envelope
from app.schemas.common import PageMeta, ok
from app.schemas.coupon import CouponOut, CouponPageData

router = APIRouter(tags=["券"])


@router.get("/coupon/list", response_model=Envelope[CouponPageData], summary="我的券")
async def list_coupons(
    status: int | None = Query(default=None, ge=1, le=4),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[CouponPageData]:
    # TODO(Phase1): coupon_pool 按 obtain_user_id 查询；不满足门槛灰显返回（不隐藏）
    data = CouponPageData(
        items=[
            CouponOut(
                id=3051,
                code="CP-3051",
                type=1,
                scope=1,
                amount=3.0,
                discount_rate=None,
                min_spend=20.0,
                merchant_id=88,
                status=1,
                valid_from=datetime.now(),
                valid_to=datetime.now() + timedelta(days=30),
            )
        ],
        page=PageMeta(page=page, page_size=page_size, total=1),
    )
    return ok(data, request_id=request_id)
