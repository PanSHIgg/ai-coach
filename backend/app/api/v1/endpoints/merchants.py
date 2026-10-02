"""商家域接口（openapi: /api/merchant/list、/api/merchant/{id}、/api/sku/catalog）。

BE5 Phase 3 真实实现：LBS 商家列表（PostGIS 球面距离 + 权重分排序）、商家详情（含在售 SKU）、
标准 SKU 目录。逻辑在 services/merchant_service.py。
"""

from fastapi import APIRouter, Depends, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_current_user, get_request_id
from app.core.errors import AppException
from app.db.session import get_db
from app.models import Merchant
from app.schemas import Envelope
from app.schemas.common import ErrorCode, ok
from app.schemas.merchant import (
    CatalogData,
    MerchantDetail,
    MerchantPageData,
)
from app.services import merchant_auth, merchant_service
from app.services.merchant_auth import MerchantPrincipal
from app.services.merchant_service import (
    MerchantCompareData,
    MerchantLoginData,
    MerchantLoginIn,
    MerchantMeData,
    MerchantOrderPageData,
    MerchantRedeemData,
    MerchantSkuListData,
    MerchantSkuToggleData,
    MerchantSkuUpdateIn,
    MerchantStatsData,
)

router = APIRouter(tags=["商家"])

# 商家自助域鉴权（独立于用户 JWT / admin 域）：scheme_name 对齐契约 MerchantBearer。
# 依赖定义在本文件内（不改 deps.py），签发/解析逻辑在 services/merchant_auth.py。
_merchant_bearer = HTTPBearer(auto_error=False, scheme_name="MerchantBearer")


async def get_current_merchant(
    credentials: HTTPAuthorizationCredentials | None = Depends(_merchant_bearer),
    session: AsyncSession = Depends(get_db),
) -> MerchantPrincipal:
    """Bearer 商家 token → MerchantPrincipal；缺失/无效/指向已删商家统一 1001。"""
    if credentials is None or not credentials.credentials:
        raise AppException(ErrorCode.UNAUTHORIZED)
    payload = merchant_auth.decode_merchant_token(credentials.credentials)
    try:
        merchant_id = int(payload.get("merchant_id"))
    except (TypeError, ValueError) as exc:
        raise AppException(ErrorCode.UNAUTHORIZED) from exc
    if await session.scalar(select(Merchant.id).where(Merchant.id == merchant_id)) is None:
        raise AppException(ErrorCode.UNAUTHORIZED)
    return MerchantPrincipal(
        merchant_id=merchant_id,
        account_id=payload.get("account_id"),
        username=payload.get("sub"),
    )


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


# ---------------------------------------------------------------------------
# G11 商家自助后台
#
# 注意：以下静态路径（/merchant/me、/merchant/skus、/merchant/orders、/merchant/stats、
# /merchant/compare、/merchant/login）必须注册在 GET /merchant/{id} 之前，否则会被
# `{id}` 路径参数先行匹配（"skus" 转 int 失败 → 422），静态路由永不可达。
# ---------------------------------------------------------------------------


@router.post(
    "/merchant/login",
    response_model=Envelope[MerchantLoginData],
    summary="商家登录（账号密码）",
)
async def merchant_login(
    payload: MerchantLoginIn,
    db: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[MerchantLoginData]:
    """登录失败统一 1001（不泄露账号是否存在）。"""
    data = await merchant_service.merchant_login(db, payload)
    return ok(data, request_id=request_id)


@router.get("/merchant/me", response_model=Envelope[MerchantMeData], summary="商家信息")
async def merchant_me(
    principal: MerchantPrincipal = Depends(get_current_merchant),
    db: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[MerchantMeData]:
    data = await merchant_service.merchant_me(db, principal.merchant_id)
    return ok(data, request_id=request_id)


@router.get(
    "/merchant/skus", response_model=Envelope[MerchantSkuListData], summary="商家选品/定价列表"
)
async def merchant_skus(
    principal: MerchantPrincipal = Depends(get_current_merchant),
    db: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[MerchantSkuListData]:
    data = await merchant_service.list_merchant_skus(db, principal.merchant_id)
    return ok(data, request_id=request_id)


@router.put(
    "/merchant/skus",
    response_model=Envelope[MerchantSkuListData],
    summary="商家选品/在区间内定价（批量）",
)
async def update_merchant_skus(
    payload: MerchantSkuUpdateIn,
    principal: MerchantPrincipal = Depends(get_current_merchant),
    db: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[MerchantSkuListData]:
    """价格越出目录区间 → 2001/400（与商家管理同口径）。"""
    data = await merchant_service.update_merchant_skus(db, principal.merchant_id, payload)
    return ok(data, request_id=request_id)


@router.post(
    "/merchant/sku/{id}/toggle",
    response_model=Envelope[MerchantSkuToggleData],
    summary="上架/下架",
)
async def toggle_merchant_sku(
    id: int,
    principal: MerchantPrincipal = Depends(get_current_merchant),
    db: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[MerchantSkuToggleData]:
    data = await merchant_service.toggle_merchant_sku(db, principal.merchant_id, id)
    return ok(data, request_id=request_id)


@router.get(
    "/merchant/orders", response_model=Envelope[MerchantOrderPageData], summary="商家订单/核销列表"
)
async def merchant_orders(
    status: int | None = Query(default=None, ge=1, le=5),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    principal: MerchantPrincipal = Depends(get_current_merchant),
    db: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[MerchantOrderPageData]:
    data = await merchant_service.list_merchant_orders(
        db, principal.merchant_id, status=status, page=page, page_size=page_size
    )
    return ok(data, request_id=request_id)


@router.post(
    "/merchant/order/{id}/redeem",
    response_model=Envelope[MerchantRedeemData],
    summary="商家核销",
)
async def redeem_merchant_order(
    id: int,
    principal: MerchantPrincipal = Depends(get_current_merchant),
    db: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[MerchantRedeemData]:
    """核销码一次性；已核销 → 5004。"""
    data = await merchant_service.redeem_merchant_order(db, principal.merchant_id, id)
    return ok(data, request_id=request_id)


@router.get("/merchant/stats", response_model=Envelope[MerchantStatsData], summary="商家数据看板")
async def merchant_stats(
    principal: MerchantPrincipal = Depends(get_current_merchant),
    db: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[MerchantStatsData]:
    data = await merchant_service.merchant_stats(db, principal.merchant_id)
    return ok(data, request_id=request_id)


@router.get(
    "/merchant/compare", response_model=Envelope[MerchantCompareData], summary="附近商家比价（按 SKU）"
)
async def compare_merchants(
    sku_id: int = Query(ge=1),
    lat: float | None = Query(default=None, ge=-90, le=90),
    lng: float | None = Query(default=None, ge=-180, le=180),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[MerchantCompareData]:
    """C 端接口（继承全局 bearerAuth）；按券后价 + 权重排序。"""
    data = await merchant_service.compare_merchants(db, sku_id=sku_id, lat=lat, lng=lng)
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
