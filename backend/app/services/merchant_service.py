"""商家域服务（BE5 Phase 3）：LBS 商家列表、商家详情、标准 SKU 目录。

口径与默认决策：
- 列表只出 audit_status=1（审核通过）且 status=1（营业）商家；category 为精确匹配。
- 距离 haversine（Python 侧算，数据量小），distance_m > radius 的商家不返回。
- 权重分排序【假设】（docs/split 01/03 仅提"商家权重排名/距离评分券排序"，无公式定义）：
    总分(0-100) = 40×拉新分 + 40×券分 + 20×过程分
    拉新分 = created_at 新→旧线性归一化到 0-1（最新=1、最旧=0；无差异时全 1）
    券分   = 该商家名下（coupon_pool.merchant_id）存在可领券池（status=1、未过有效期、
             有余量）则 1 否则 0
    过程分 = rating / 5
  不传坐标按 id 升序；传坐标按总分降序，同分按距离升序、再按 id。
- 详情：不存在/未过审 → 3001(404)；status=0 → 5001(409)；skus 只含 merchant_sku.status=1。
- 目录：sku_catalog 全量（含 min_price/max_price 限价区间），可 category 过滤。
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppException
from app.models import Merchant, MerchantSku, SkuCatalog
from app.schemas.common import ErrorCode, PageMeta
from app.schemas.merchant import (
    CatalogData,
    CatalogItem,
    MerchantBrief,
    MerchantDetail,
    MerchantPageData,
    SkuOut,
)

_TZ = timezone(timedelta(hours=8))
_EARTH_R_M = 6371000.0

# 权重分系数：拉新 40% + 券 40% + 过程 20%（总分 0-100）
_W_FRESH = 40.0
_W_COUPON = 40.0
_W_PROCESS = 20.0


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> int:
    """两经纬度球面距离（米，四舍五入取整）。"""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return int(round(_EARTH_R_M * 2 * math.asin(math.sqrt(a))))


def _norm_freshness(created: list[datetime]) -> dict[int, float]:
    """created_at 新→旧线性归一化 0-1（index 越靠前越新分越高）；无差异时全 1。"""
    ordered = sorted(range(len(created)), key=lambda i: created[i], reverse=True)
    n = len(ordered)
    if n <= 1:
        return {i: 1.0 for i in range(n)}
    scores: dict[int, float] = {}
    for rank, idx in enumerate(ordered):
        scores[idx] = 1.0 - rank / (n - 1)
    return scores


async def list_merchants(
    db: AsyncSession,
    *,
    lat: float | None,
    lng: float | None,
    radius: int,
    category: str | None,
    page: int,
    page_size: int,
) -> MerchantPageData:
    has_geo = lat is not None and lng is not None
    stmt = select(Merchant).where(Merchant.audit_status == 1, Merchant.status == 1)
    if category:
        stmt = stmt.where(Merchant.category == category)
    stmt = stmt.order_by(Merchant.id)
    rows = (await db.scalars(stmt)).all()

    # 券分：一次查出有可领券池的商家集合（coupon_pool.merchant_id 关联，不含通用券）
    now = datetime.now(_TZ)
    merchant_ids = [m.id for m in rows]
    coupon_ok_ids: set[int] = set()
    if merchant_ids:
        from app.models import CouponPool

        pool_stmt = select(CouponPool.merchant_id).where(
            CouponPool.status == 1,
            CouponPool.merchant_id.in_(merchant_ids),
            or_(CouponPool.total_count == -1, CouponPool.granted_count < CouponPool.total_count),
            or_(CouponPool.valid_from.is_(None), CouponPool.valid_from <= now),
            or_(CouponPool.valid_to.is_(None), CouponPool.valid_to >= now),
        )
        coupon_ok_ids = set(await db.scalars(pool_stmt))

    fresh_scores = _norm_freshness([m.created_at for m in rows])

    items: list[tuple[MerchantBrief, float, int]] = []  # (brief, 总分, distance)
    for idx, m in enumerate(rows):
        # 与 detail 路径同口径：商家坐标缺失时不算距离（distance_m=None）
        geo_ok = has_geo and m.lat is not None and m.lng is not None
        distance = haversine_m(lat, lng, float(m.lat), float(m.lng)) if geo_ok else None
        if distance is not None and distance > radius:
            continue
        total = (
            _W_FRESH * fresh_scores[idx]
            + _W_COUPON * (1.0 if m.id in coupon_ok_ids else 0.0)
            + _W_PROCESS * (float(m.rating) / 5.0)
        )
        brief = MerchantBrief(
            id=m.id,
            name=m.name,
            category=m.category,
            distance_m=distance,
            rating=round(float(m.rating), 1),
            cover_url=None,
            status=m.status,
        )
        items.append((brief, round(total, 1), distance or 0))

    if has_geo:
        items.sort(key=lambda t: (-t[1], t[2], t[0].id))
    else:
        items.sort(key=lambda t: t[0].id)

    total_count = len(items)
    start = (page - 1) * page_size
    page_items = [brief for brief, _, _ in items[start : start + page_size]]
    return MerchantPageData(items=page_items, page=PageMeta(page=page, page_size=page_size, total=total_count))


async def get_merchant_detail(
    db: AsyncSession, merchant_id: int, *, lat: float | None, lng: float | None
) -> MerchantDetail:
    m = await db.get(Merchant, merchant_id)
    # 未过审/驳回对 C 端不可见，与不存在同口径
    if m is None or m.audit_status != 1:
        raise AppException(ErrorCode.NOT_FOUND)
    if m.status == 0:
        raise AppException(ErrorCode.MERCHANT_CLOSED)

    sku_rows = (
        await db.execute(
            select(MerchantSku, SkuCatalog)
            .join(SkuCatalog, MerchantSku.catalog_id == SkuCatalog.id)
            .where(MerchantSku.merchant_id == merchant_id, MerchantSku.status == 1)
            .order_by(MerchantSku.id)
        )
    ).all()

    distance = None
    if lat is not None and lng is not None and m.lat is not None and m.lng is not None:
        distance = haversine_m(lat, lng, float(m.lat), float(m.lng))

    return MerchantDetail(
        id=m.id,
        name=m.name,
        category=m.category,
        address=m.address,
        lat=float(m.lat) if m.lat is not None else None,
        lng=float(m.lng) if m.lng is not None else None,
        phone=m.phone,
        rating=round(float(m.rating), 1),
        status=m.status,
        distance_m=distance,
        skus=[
            SkuOut(id=ms.id, name=cat.name, price=float(ms.price), stock=ms.stock)
            for ms, cat in sku_rows
        ],
    )


async def list_catalog(db: AsyncSession, category: str | None) -> CatalogData:
    stmt = select(SkuCatalog)
    if category:
        stmt = stmt.where(SkuCatalog.category == category)
    stmt = stmt.order_by(SkuCatalog.id)
    rows = (await db.scalars(stmt)).all()
    return CatalogData(
        items=[
            CatalogItem(
                id=c.id,
                code=c.code,
                name=c.name,
                category=c.category,
                calories_low=c.calories_low,
                calories_high=c.calories_high,
                base_price=float(c.base_price),
                min_price=float(c.min_price),
                max_price=float(c.max_price),
                unit=c.unit,
            )
            for c in rows
        ]
    )
