"""券域接口（openapi: /api/coupon/list）。

Phase 3 BE6：真实查询（obtain_user_id 行级隔离）+ scope/status 过滤 + 惰性过期。
惰性过期【假设】只改响应不改库：status=1 且 valid_to<now 的券按 3过期 展示；
status 过滤口径：1未用排除已过期，3过期含「库里仍 1 但已过有效期」的券。
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_current_user, get_request_id
from app.db.session import get_db
from app.models import Coupon, ExclusiveOffer
from app.schemas import Envelope
from app.schemas.common import PageMeta, ok
from app.schemas.coupon import CouponOut, CouponPageData

router = APIRouter(tags=["券"])


class ExclusiveCouponData(BaseModel):
    """专属优惠（异业联盟券）列表：items 复用契约 CouponOut 结构（scope=3 异业）。"""

    model_config = ConfigDict(from_attributes=True)

    items: list[CouponOut]


def _display_status(coupon: Coupon, now: datetime) -> int:
    """展示态：未用但已过有效期 → 3过期（不改库）。"""
    if coupon.status == 1 and coupon.valid_to is not None and coupon.valid_to < now:
        return 3
    return coupon.status


@router.get("/coupon/list", response_model=Envelope[CouponPageData], summary="我的券")
async def list_coupons(
    status: int | None = Query(default=None, ge=1, le=4),
    scope: int | None = Query(default=None, ge=1, le=4),  # 【假设】additive 参数，契约向后兼容
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
    session: AsyncSession = Depends(get_db),
) -> Envelope[CouponPageData]:
    now = datetime.now(UTC)
    base = select(Coupon).where(Coupon.obtain_user_id == user.id)
    count_stmt = select(func.count()).select_from(Coupon).where(Coupon.obtain_user_id == user.id)
    if scope is not None:
        base = base.where(Coupon.scope == scope)
        count_stmt = count_stmt.where(Coupon.scope == scope)
    if status is not None:
        if status == 1:  # 未用：排除已过有效期的
            cond = and_(
                Coupon.status == 1,
                or_(Coupon.valid_to.is_(None), Coupon.valid_to >= now),
            )
        elif status == 3:  # 过期：库内 3 或「未用但已过有效期」
            cond = or_(
                Coupon.status == 3,
                and_(Coupon.status == 1, Coupon.valid_to.is_not(None), Coupon.valid_to < now),
            )
        else:
            cond = Coupon.status == status
        base = base.where(cond)
        count_stmt = count_stmt.where(cond)

    total = await session.scalar(count_stmt)
    rows = (
        (
            await session.execute(
                base.order_by(Coupon.created_at.desc(), Coupon.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    items = []
    for c in rows:
        out = CouponOut.model_validate(c)
        out.status = _display_status(c, now)
        items.append(out)
    data = CouponPageData(
        items=items, page=PageMeta(page=page, page_size=page_size, total=total or 0)
    )
    return ok(data, request_id=request_id)


@router.get(
    "/coupon/exclusive",
    response_model=Envelope[ExclusiveCouponData],
    summary="专属优惠（异业联盟券目录）",
)
async def list_exclusive_coupons(
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
    session: AsyncSession = Depends(get_db),
) -> Envelope[ExclusiveCouponData]:
    """上架（status=1）且未过期（valid_to 为空或未到）的异业联盟券目录。

    【假设】`exclusive_offer` 目录映射契约 `CouponOut`：scope 恒为 3（异业）；
    code 由 offer.id 合成（目录表无 code 列）；coupon_amount>0 → type 1（满减），
    否则 type 3（免费/体验）；min_spend/merchant_id/discount_rate/valid_from 目录无对应列，置默认。
    """
    now = datetime.now(UTC)
    rows = (
        (
            await session.execute(
                select(ExclusiveOffer)
                .where(
                    ExclusiveOffer.status == 1,
                    or_(ExclusiveOffer.valid_to.is_(None), ExclusiveOffer.valid_to >= now),
                )
                .order_by(ExclusiveOffer.id)
            )
        )
        .scalars()
        .all()
    )
    items = [
        CouponOut(
            id=o.id,
            code=f"EX-{o.id:06d}",
            type=1 if float(o.coupon_amount or 0) > 0 else 3,
            scope=3,
            amount=float(o.coupon_amount or 0),
            discount_rate=None,
            min_spend=0,
            merchant_id=None,
            status=1,
            valid_from=None,
            valid_to=o.valid_to,
        )
        for o in rows
    ]
    return ok(ExclusiveCouponData(items=items), request_id=request_id)
