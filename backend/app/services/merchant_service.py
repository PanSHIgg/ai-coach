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
- 权重保护/清退（§6.3.4，R-01）：`evaluate_partner_levels` 按权重分排名回写 partner_level
  （前 20% 战略合作 / 前 20%~50% 优选保护 / 其余普通），`evict_zero_contribution` 清退
  连续零贡献商家。阈值/口径均为【假设】。
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppException
from app.models import CouponPool, Merchant, MerchantSku, RedeemLog, SkuCatalog
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

# 权重保护比例【假设】（§6.3.4 仅给比例，未给名次取整/并列规则）
_PARTNER_TOP_RATIO = 0.20  # 名次前 20% → 战略合作
_PARTNER_PROTECT_RATIO = 0.50  # 名次前 50% → 优选合作保护
# 连续零贡献清退【假设】
_ZERO_CONTRIB_DAYS = 14  # 连续 N 天零贡献 → 清退
_EVICTED_STATUS = 0  # 清退动作：status=0（停业）+ partner_level=0


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


async def _coupon_ok_ids(db: AsyncSession, merchant_ids: list[int]) -> set[int]:
    """一次查出有可领券池的商家集合（coupon_pool.merchant_id 关联，不含通用券）。"""
    if not merchant_ids:
        return set()
    now = datetime.now(_TZ)
    pool_stmt = select(CouponPool.merchant_id).where(
        CouponPool.status == 1,
        CouponPool.merchant_id.in_(merchant_ids),
        or_(CouponPool.total_count == -1, CouponPool.granted_count < CouponPool.total_count),
        or_(CouponPool.valid_from.is_(None), CouponPool.valid_from <= now),
        or_(CouponPool.valid_to.is_(None), CouponPool.valid_to >= now),
    )
    return set(await db.scalars(pool_stmt))


async def _weight_scores(db: AsyncSession, rows: list[Merchant]) -> dict[int, float]:
    """权重分（0-100，口径见模块 docstring）：列表排序与合作伙伴评估共用同一口径。"""
    if not rows:
        return {}
    coupon_ok_ids = await _coupon_ok_ids(db, [m.id for m in rows])
    fresh_scores = _norm_freshness([m.created_at for m in rows])
    return {
        m.id: round(
            _W_FRESH * fresh_scores[idx]
            + _W_COUPON * (1.0 if m.id in coupon_ok_ids else 0.0)
            + _W_PROCESS * (float(m.rating) / 5.0),
            1,
        )
        for idx, m in enumerate(rows)
    }


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

    scores = await _weight_scores(db, list(rows))

    items: list[tuple[MerchantBrief, float, int]] = []  # (brief, 总分, distance)
    for m in rows:
        # 与 detail 路径同口径：商家坐标缺失时不算距离（distance_m=None）
        geo_ok = has_geo and m.lat is not None and m.lng is not None
        distance = haversine_m(lat, lng, float(m.lat), float(m.lng)) if geo_ok else None
        if distance is not None and distance > radius:
            continue
        brief = MerchantBrief(
            id=m.id,
            name=m.name,
            category=m.category,
            distance_m=distance,
            rating=round(float(m.rating), 1),
            cover_url=None,
            status=m.status,
            partner_level=int(m.partner_level or 0),
        )
        items.append((brief, scores[m.id], distance or 0))

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
        partner_level=int(m.partner_level or 0),
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


# ---------------------------------------------------------------------------
# 权重保护 / 清退（§6.3.4，R-01）
# ---------------------------------------------------------------------------


async def evaluate_partner_levels(db: AsyncSession) -> dict[int, int]:
    """按权重分排名批量评估合作层级（§6.3.4）并回写 merchant.partner_level。

    【假设】名次（1 起）规则：
    - 名次 <= ceil(20%×N) → 2（战略合作独家区域）；
    - 名次 <= ceil(50%×N) → 1（优选合作保护）；
    - 其余 → 0（普通）。
    排序同列表：权重分降序、同分按 id 升序；仅评估 audit_status=1 且 status=1 在营商家。
    返回 {merchant_id: partner_level}。提交事务。
    """
    rows = list(
        (await db.scalars(select(Merchant).where(Merchant.audit_status == 1, Merchant.status == 1)))
        .all()
    )
    scores = await _weight_scores(db, rows)
    ordered = sorted(rows, key=lambda m: (-scores.get(m.id, 0.0), m.id))
    n = len(ordered)
    top_n = math.ceil(n * _PARTNER_TOP_RATIO)
    protect_n = math.ceil(n * _PARTNER_PROTECT_RATIO)
    result: dict[int, int] = {}
    for rank, m in enumerate(ordered, start=1):
        if rank <= top_n:
            level = 2
        elif rank <= protect_n:
            level = 1
        else:
            level = 0
        m.partner_level = level
        result[m.id] = level
    await db.commit()
    return result


async def evict_zero_contribution(
    db: AsyncSession, *, zero_days: int = _ZERO_CONTRIB_DAYS, now: datetime | None = None
) -> list[int]:
    """连续 N 天零贡献清退（§6.3.4）并回填 last_contribution_at。

    【假设】零贡献口径：近 zero_days 天内无成功核销（redeem_log.result=1）。
    - 有贡献者：last_contribution_at = 最近一次成功核销时间（不回退层级/状态）；
    - 无贡献且建店已满 zero_days 天（created_at <= 窗口起点）：清退 → partner_level=0
      且 status=0（停业）；建店未满窗口的新商家不清退（避免误伤，对齐「连续」语义）。
    返回被清退商家 id 列表。提交事务。
    """
    ref = now or datetime.now(_TZ)
    since = ref - timedelta(days=zero_days)
    rows = list(
        (await db.scalars(select(Merchant).where(Merchant.audit_status == 1, Merchant.status == 1)))
        .all()
    )
    merchant_ids = [m.id for m in rows]
    latest: dict[int, datetime] = {}
    if merchant_ids:
        latest_rows = (
            await db.execute(
                select(RedeemLog.merchant_id, func.max(RedeemLog.created_at))
                .where(
                    RedeemLog.merchant_id.in_(merchant_ids),
                    RedeemLog.result == 1,
                    RedeemLog.created_at >= since,
                )
                .group_by(RedeemLog.merchant_id)
            )
        ).all()
        latest = {mid: ts for mid, ts in latest_rows if mid is not None and ts is not None}

    evicted: list[int] = []
    for m in rows:
        if m.id in latest:
            m.last_contribution_at = latest[m.id]
        elif m.created_at is not None and m.created_at <= since:
            m.partner_level = 0
            m.status = _EVICTED_STATUS
            evicted.append(m.id)
    await db.commit()
    return evicted
