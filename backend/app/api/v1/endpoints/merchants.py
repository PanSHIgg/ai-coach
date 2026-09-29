"""商家域接口（openapi: /api/merchant/list、/api/merchant/{id}、/api/sku/catalog）。

BE5 Phase 3 真实实现：LBS 商家列表（haversine 距离 + 权重分排序）、商家详情（含在售 SKU）、
标准 SKU 目录。逻辑在 services/merchant_service.py。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_current_user, get_request_id
from app.db.session import get_db
from app.schemas import Envelope
from app.schemas.common import ok
from app.schemas.merchant import (
    CatalogData,
    MerchantDetail,
    MerchantPageData,
)
from app.services import merchant_service

router = APIRouter(tags=["商家"])


@router.get("/merchant/list", response_model=Envelope[MerchantPageData], summary="商家列表（LBS）")
async def list_merchants(
    lat: float | None = Query(default=None, ge=-90, le=90),
    lng: float | None = Query(default=None, ge=-180, le=180),
    radius: int = Query(default=3000),
    category: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[MerchantPageData]:
    data = await merchant_service.list_merchants(
        db, lat=lat, lng=lng, radius=radius, category=category, page=page, page_size=page_size
    )
    return ok(data, request_id=request_id)


@router.get("/merchant/{id}", response_model=Envelope[MerchantDetail], summary="商家详情")
async def get_merchant(
    id: int,
    lat: float | None = Query(default=None, ge=-90, le=90),
    lng: float | None = Query(default=None, ge=-180, le=180),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[MerchantDetail]:
    data = await merchant_service.get_merchant_detail(db, id, lat=lat, lng=lng)
    return ok(data, request_id=request_id)


@router.get(
    "/sku/catalog",
    response_model=Envelope[CatalogData],
    summary="标准目录（平台运营维护）",
)
async def list_sku_catalog(
    category: str | None = Query(default=None),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[CatalogData]:
    data = await merchant_service.list_catalog(db, category)
    return ok(data, request_id=request_id)
