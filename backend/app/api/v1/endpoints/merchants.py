"""商家域接口（openapi: /api/merchant/list、/api/merchant/{id}、/api/sku/catalog）。"""

from fastapi import APIRouter, Depends, Query

from app.api.deps import CurrentUser, get_current_user, get_request_id
from app.schemas import Envelope
from app.schemas.common import PageMeta, ok
from app.schemas.merchant import (
    CatalogData,
    CatalogItem,
    MerchantBrief,
    MerchantDetail,
    MerchantPageData,
    SkuOut,
)

router = APIRouter(tags=["商家"])


@router.get("/merchant/list", response_model=Envelope[MerchantPageData], summary="商家列表（LBS）")
async def list_merchants(
    lat: float | None = Query(default=None),
    lng: float | None = Query(default=None),
    radius: int = Query(default=3000),
    category: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[MerchantPageData]:
    # TODO(Phase1): merchant 表 + 经纬度距离排序（【假设】不传坐标按默认城市）
    data = MerchantPageData(
        items=[
            MerchantBrief(
                id=88, name="轻食一号店", category="轻食", distance_m=350,
                rating=4.8, cover_url="https://cos.example.com/m/88.png", status=1,
            )
        ],
        page=PageMeta(page=page, page_size=page_size, total=1),
    )
    return ok(data, request_id=request_id)


@router.get("/merchant/{id}", response_model=Envelope[MerchantDetail], summary="商家详情")
async def get_merchant(
    id: int,
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[MerchantDetail]:
    # TODO(Phase1): 查 merchant + merchant_sku；停业返回 5001
    data = MerchantDetail(
        id=id,
        name="轻食一号店",
        category="轻食",
        address="XX路1号",
        lat=31.2304,
        lng=121.4737,
        phone="021-0000000",
        rating=4.8,
        status=1,
        distance_m=350,
        skus=[SkuOut(id=12, name="鸡胸肉沙拉", price=28.0, stock=99)],
    )
    return ok(data, request_id=request_id)


@router.get("/sku/catalog", response_model=Envelope[CatalogData], summary="标准目录（平台运营维护）")
async def list_sku_catalog(
    category: str | None = Query(default=None),
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[CatalogData]:
    # TODO(Phase1): sku_catalog 表按 category 过滤（含限价区间）
    data = CatalogData(
        items=[
            CatalogItem(
                id=1, code="FD-001", name="鸡胸肉沙拉", category="轻食",
                calories_low=300, calories_high=500, base_price=28.0,
                min_price=20.0, max_price=40.0, unit="份",
            )
        ]
    )
    return ok(data, request_id=request_id)
