"""管理域接口（openapi: /api/admin/*）。

BE9 管理 API：登录/商家审核/选品定价/券池/发放/订单监控。
admin token 与 C 端 JWT 同签名体系但 subject 指向 admin_user.id，经
get_current_admin 独立校验（C 端 token 无对应 admin 账号 -> 1001）。
"""

from datetime import date as _date

from fastapi import APIRouter, Depends, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_request_id
from app.core.errors import AppException
from app.core.security import decode_token
from app.db.session import get_db
from app.models import AdminUser
from app.schemas import DashboardData, Envelope
from app.schemas.admin import (
    AdminAuditIn,
    AdminAuditPageData,
    AdminCouponPoolIn,
    AdminCouponPoolOut,
    AdminCouponPoolPageData,
    AdminGrantData,
    AdminGrantIn,
    AdminLoginData,
    AdminLoginIn,
    AdminMerchantOut,
    AdminMerchantPageData,
    AdminMerchantSkuData,
    AdminMerchantSkuIn,
    AdminReviewData,
    AdminReviewIn,
    AdminSkuCatalogIn,
    AdminSkuStatusIn,
)
from app.schemas.common import ErrorCode, ok
from app.schemas.merchant import CatalogData, CatalogItem
from app.schemas.order import OrderPageData
from app.services import admin_service, merchant_service
from app.services.admin_service import AdminPrincipal

router = APIRouter(tags=["管理"])

_admin_bearer = HTTPBearer(auto_error=False, scheme_name="bearerAuth")


async def get_current_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(_admin_bearer),
    session: AsyncSession = Depends(get_db),
) -> AdminPrincipal:
    """Bearer JWT -> AdminPrincipal；缺失/无效/指向已删账号统一 1001。

    role/merchant_id 取 DB 现值（非 token claim），保证账号角色变更即时生效。
    """
    if credentials is None or not credentials.credentials:
        raise AppException(ErrorCode.UNAUTHORIZED)
    payload = decode_token(credentials.credentials, expected_type="access", expected_dom="admin")
    try:
        admin_id = int(payload.get("sub", ""))
    except (TypeError, ValueError) as exc:
        raise AppException(ErrorCode.UNAUTHORIZED) from exc
    admin = (
        await session.execute(select(AdminUser).where(AdminUser.id == admin_id))
    ).scalar_one_or_none()
    if admin is None:
        raise AppException(ErrorCode.UNAUTHORIZED)
    return AdminPrincipal(
        id=admin.id, role=admin.role, merchant_id=admin.merchant_id, username=admin.username
    )


# ---- 登录（security: []，无需认证）----


@router.post(
    "/admin/login", response_model=Envelope[AdminLoginData], summary="管理员登录（账号密码）"
)
async def admin_login(
    payload: AdminLoginIn,
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[AdminLoginData]:
    data = await admin_service.login(session, payload)
    return ok(data, request_id=request_id)


# ---- 商家审核 ----


@router.get(
    "/admin/merchants",
    response_model=Envelope[AdminMerchantPageData],
    summary="商家列表（含审核状态；audit_status 过滤）",
)
async def admin_list_merchants(
    audit_status: int | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    admin: AdminPrincipal = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[AdminMerchantPageData]:
    data = await admin_service.list_merchants(session, admin, audit_status, page, page_size)
    return ok(data, request_id=request_id)


@router.post(
    "/admin/merchants/{id}/audit",
    response_model=Envelope[AdminMerchantOut],
    summary="商家入驻审核（1通过 / 2驳回）",
)
async def admin_audit_merchant(
    id: int,
    payload: AdminAuditIn,
    admin: AdminPrincipal = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[AdminMerchantOut]:
    data = await admin_service.audit_merchant(session, admin, id, payload)
    return ok(data, request_id=request_id)


# ---- 商家选品定价 ----


@router.post(
    "/admin/merchant-skus",
    response_model=Envelope[AdminMerchantSkuData],
    summary="商家选品定价（已存在则更新价格/库存；价格越出目录区间 → 2001/422）",
)
async def admin_upsert_merchant_sku(
    payload: AdminMerchantSkuIn,
    admin: AdminPrincipal = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[AdminMerchantSkuData]:
    data = await admin_service.upsert_merchant_sku(session, admin, payload)
    return ok(data, request_id=request_id)


@router.post(
    "/admin/merchant-skus/{id}/status",
    response_model=Envelope[AdminMerchantSkuData],
    summary="商家 SKU 上下架",
)
async def admin_set_merchant_sku_status(
    id: int,
    payload: AdminSkuStatusIn,
    admin: AdminPrincipal = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[AdminMerchantSkuData]:
    data = await admin_service.set_sku_status(session, admin, id, payload)
    return ok(data, request_id=request_id)


@router.get(
    "/admin/sku-catalog",
    response_model=Envelope[CatalogData],
    summary="标准目录查询（管理侧；与 C 端 /api/sku/catalog 同数据，供选品定价下拉）",
)
async def admin_list_sku_catalog(
    category: str | None = Query(default=None),
    admin: AdminPrincipal = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[CatalogData]:
    data = await merchant_service.list_catalog(session, category)
    return ok(data, request_id=request_id)


@router.post(
    "/admin/sku-catalog",
    response_model=Envelope[CatalogItem],
    summary="新建标准目录项（平台运营维护，商家只选不建；重名 2001/422）",
)
async def admin_create_sku_catalog(
    payload: AdminSkuCatalogIn,
    admin: AdminPrincipal = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[CatalogItem]:
    data = await admin_service.create_sku_catalog(session, admin, payload)
    return ok(data, request_id=request_id)


@router.put(
    "/admin/sku-catalog/{id}",
    response_model=Envelope[CatalogItem],
    summary="编辑标准目录项（平台运营维护；不存在 3001/404，重名 2001/422）",
)
async def admin_update_sku_catalog(
    id: int,
    payload: AdminSkuCatalogIn,
    admin: AdminPrincipal = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[CatalogItem]:
    data = await admin_service.update_sku_catalog(session, admin, id, payload)
    return ok(data, request_id=request_id)


# ---- 券池 ----


@router.get(
    "/admin/coupon-pools",
    response_model=Envelope[AdminCouponPoolPageData],
    summary="券池列表",
)
async def admin_list_coupon_pools(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    admin: AdminPrincipal = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[AdminCouponPoolPageData]:
    data = await admin_service.list_coupon_pools(session, admin, page, page_size)
    return ok(data, request_id=request_id)


@router.post(
    "/admin/coupon-pools",
    response_model=Envelope[AdminCouponPoolOut],
    summary="创建券池（券发放唯一源头）",
)
async def admin_create_coupon_pool(
    payload: AdminCouponPoolIn,
    admin: AdminPrincipal = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[AdminCouponPoolOut]:
    data = await admin_service.create_coupon_pool(session, admin, payload)
    return ok(data, request_id=request_id)


@router.post(
    "/admin/coupon-pools/{id}/grant",
    response_model=Envelope[AdminGrantData],
    summary="从券池向用户发放券（测试/补贴通道）",
)
async def admin_grant_coupon(
    id: int,
    payload: AdminGrantIn,
    admin: AdminPrincipal = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[AdminGrantData]:
    # 契约入参带 pool_id，与路径 id 双保险：不一致视为参数错误
    if payload.pool_id != id:
        raise AppException(ErrorCode.VALIDATION_ERROR, "pool_id 与路径 id 不一致")
    data = await admin_service.grant_coupons(session, admin, payload)
    return ok(data, request_id=request_id)


# ---- 订单监控 ----


@router.get(
    "/admin/orders",
    response_model=Envelope[OrderPageData],
    summary="订单监控（全量分页，商家角色仅见本商家）",
)
async def admin_list_orders(
    status: int | None = Query(default=None),
    merchant_id: int | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    admin: AdminPrincipal = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[OrderPageData]:
    data = await admin_service.list_orders(session, admin, status, merchant_id, page, page_size)
    return ok(data, request_id=request_id)


# ---- 运营看板（IS-008: 真实聚合查询）----


@router.get("/admin/dashboard", response_model=Envelope[DashboardData], summary="运营看板")
async def get_admin_dashboard(
    date: _date | None = Query(default=None),
    admin: AdminPrincipal = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[DashboardData]:
    """IS-008: 真实聚合查询替代硬编码数据。"""
    data = await admin_service.get_dashboard(session, date)
    return ok(data, request_id=request_id)


# ---- 内容审核队列（Phase 4 ADM）----


@router.get(
    "/admin/audit/list",
    response_model=Envelope[AdminAuditPageData],
    summary="内容审核队列（review；status 过滤 0待审 1通过 2驳回）",
)
async def admin_list_audit(
    status: int | None = Query(default=None, ge=0, le=2),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    admin: AdminPrincipal = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[AdminAuditPageData]:
    data = await admin_service.list_audit(session, admin, status, page, page_size)
    return ok(data, request_id=request_id)


@router.post(
    "/admin/audit/{id}/review",
    response_model=Envelope[AdminReviewData],
    summary="处理审核（1通过 / 2驳回）",
)
async def admin_review_audit(
    id: int,
    payload: AdminReviewIn,
    admin: AdminPrincipal = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[AdminReviewData]:
    data = await admin_service.review_audit(session, admin, id, payload)
    return ok(data, request_id=request_id)
