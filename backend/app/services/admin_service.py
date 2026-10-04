"""管理后台服务（BE9）：登录/商家审核/选品定价/券池/发放/订单监控。

权限模型（AdminPrincipal.role）：
- 1 超管 / 2 运营：全功能；
- 3 商家：仅本商家范围——目标资源商家必须与自身 merchant_id 匹配（否则 1002），
  平台级操作（商家审核、券池管理/发放）一律 1002；订单监控强制注入本商家过滤。

默认决策 / 假设：
- 【假设】admin token：create_access_token(str(admin.id), role=..., merchant_id=...)，
  与 C 端 token 同签名体系但 subject 指向 admin_user.id，独立校验互不通用。
- 【假设】merchant 表无 audit_reason/cover_url 列（模型只读冻结）：audit_reason 仅在
  审核响应内内存回显、不持久化；cover_url 恒 None。
- 【假设】merchant_sku 无 updated_at 列：AdminMerchantSkuData.updated_at 恒 None。
- 【假设】券池 total_count=-1 表示不限量，发放不校验余量。
- 【假设】admin 发放券 obtain_way=3（平台补贴，契约"测试/补贴通道"）。
- 【假设】AdminGrantData.granted_count 返回发放后的券池累计已发放量。
"""

from __future__ import annotations

import secrets
import string
from datetime import date, datetime, time, timedelta, timezone

from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppException
from app.core.logging import get_logger
from app.core.rate_limit import incr_window
from app.core.security import (
    create_access_token,
    hash_password,
    reject_weak_password,
    verify_password,
)
from app.db.redis import get_redis
from app.models import (
    AdminUser,
    AiDialog,
    CommunityComment,
    CommunityPost,
    Coupon,
    CouponPool,
    MealRecord,
    Merchant,
    MerchantSku,
    Order,
    Review,
    SkuCatalog,
    SportRecord,
    User,
)
from app.schemas.admin import (
    AdminAccountIn,
    AdminAccountOut,
    AdminAccountPageData,
    AdminAuditIn,
    AdminAuditItem,
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
    AdminPasswordResetIn,
    AdminReviewData,
    AdminReviewIn,
    AdminSkuCatalogIn,
    AdminSkuStatusIn,
)
from app.schemas.common import ErrorCode, PageMeta
from app.schemas.coupon import CouponOut
from app.schemas.merchant import CatalogItem
from app.schemas.order import OrderBrief, OrderPageData

logger = get_logger(__name__)

_ALNUM = string.ascii_uppercase + string.digits  # 券码字符集（CP + 8 位大写）
_CODE_ATTEMPTS = 8  # code 冲突重试上限

# IS-007: admin 登录失败锁定配置
_ADMIN_LOGIN_MAX_FAILURES = 5  # 连续失败次数
_ADMIN_LOGIN_LOCK_SECONDS = 15 * 60  # 锁定 15 分钟

# 时区：与 record_service/account 保持一致（UTC+8）
_TZ = timezone(timedelta(hours=8))


class AdminPrincipal(BaseModel):
    """get_current_admin 解析出的管理员身份（role/merchant_id 取 DB 现值）。"""

    id: int
    role: int
    merchant_id: int | None = None
    username: str


# ---- 权限辅助 ----


def ensure_manager(principal: AdminPrincipal) -> None:
    """平台级操作：仅超管/运营（role 1/2），商家角色 1002。"""
    if principal.role not in (1, 2):
        raise AppException(ErrorCode.FORBIDDEN)


def ensure_super(principal: AdminPrincipal) -> None:
    """超管专属操作（如创建运营账号）：仅 role=1，其余 1002。"""
    if principal.role != 1:
        raise AppException(ErrorCode.FORBIDDEN)


def ensure_scope(principal: AdminPrincipal, merchant_id: int | None) -> None:
    """本商家范围校验：role 3 的 merchant_id 必须与目标资源商家匹配。"""
    if principal.role == 3 and merchant_id != principal.merchant_id:
        raise AppException(ErrorCode.FORBIDDEN)


# ---- 登录 ----


async def _check_admin_login_lock(username: str) -> None:
    """IS-007: 检查账号是否被锁定（连续失败 5 次锁 15 分钟）。"""
    try:
        redis = await get_redis()
        if redis is None:
            return  # Redis 不可用时降级（不锁定）
        lock_key = f"admin_login_lock:{username}"
        if await redis.exists(lock_key):
            raise AppException(
                ErrorCode.RATE_LIMITED,
                f"账号已被锁定，请 {_ADMIN_LOGIN_LOCK_SECONDS // 60} 分钟后重试",
            )
    except AppException:
        raise  # 锁定异常必须向上传播，不能被吞掉
    except Exception as exc:
        logger.warning(f"检查 admin 登录锁定失败: {exc}")


async def _record_admin_login_failure(username: str) -> None:
    """IS-007: 记录登录失败，达到阈值后锁定账号。"""
    try:
        fail_key = f"admin_login_fail:{username}"
        lock_key = f"admin_login_lock:{username}"

        # 使用原子递增窗口
        count = await incr_window(fail_key, _ADMIN_LOGIN_LOCK_SECONDS)

        if count is None:
            # Redis 不可用，降级（不锁定）
            return

        # 达到阈值则锁定
        if count >= _ADMIN_LOGIN_MAX_FAILURES:
            redis = await get_redis()
            if redis is not None:
                await redis.set(lock_key, 1, ex=_ADMIN_LOGIN_LOCK_SECONDS)
                await redis.delete(fail_key)
                logger.warning(
                    f"admin 账号 {username} 因连续 {_ADMIN_LOGIN_MAX_FAILURES} 次登录失败被锁定"
                )
    except Exception as exc:
        logger.warning(f"记录 admin 登录失败失败: {exc}")


async def _clear_admin_login_failures(username: str) -> None:
    """IS-007: 登录成功后清除失败计数。"""
    try:
        redis = await get_redis()
        if redis is None:
            return
        await redis.delete(f"admin_login_fail:{username}")
    except Exception as exc:
        logger.warning(f"清除 admin 登录失败计数失败: {exc}")


async def login(session: AsyncSession, payload: AdminLoginIn) -> AdminLoginData:
    """admin 登录（IS-007: 含失败锁定机制）。"""
    # 检查是否被锁定
    await _check_admin_login_lock(payload.username)

    admin = (
        await session.execute(select(AdminUser).where(AdminUser.username == payload.username))
    ).scalar_one_or_none()
    if admin is None or not verify_password(payload.password, admin.password_hash):
        # 记录失败
        await _record_admin_login_failure(payload.username)
        raise AppException(ErrorCode.UNAUTHORIZED)
    if admin.role == 4:
        # 教练（G1）有独立教练端 /api/coach/login；放行 role=4 会在 admin web 前端
        # 触发路由门禁无限重定向（meta.roles 均不含 4），此处直接拒绝并指路。
        raise AppException(ErrorCode.FORBIDDEN, "教练账号请使用教练端登录")

    # 登录成功，清除失败计数
    await _clear_admin_login_failures(payload.username)

    token = create_access_token(
        str(admin.id), dom="admin", role=admin.role, merchant_id=admin.merchant_id
    )
    return AdminLoginData(
        token=token,
        role=admin.role,
        merchant_id=admin.merchant_id,
        username=admin.username,
    )


# ---- 账号管理（超管/运营开通后台账号）----


def _ensure_account_create_allowed(principal: AdminPrincipal, role: int) -> None:
    """创建权限分级：超管可建 1/2/3；运营仅可建 3；越界/4 一律 2001 参数校验。

    - 白名单先落地：DB 有 `CHECK (role IN (1,2,3,4))`，若放行越界值会撞约束 →
      IntegrityError → 全局 handler → 500（违反 AGENTS §7.2「参数校验 422/2001」），
      故入库前用白名单拦下；role=4（教练）也走 2001，不走 1002。
    - 建超管/运营账号（role 1/2）是超管专属，由 `ensure_super` 显式守护（其余角色 1002）；
      建商家账号（role=3）超管与运营均可。
    """
    if role not in (1, 2, 3):
        if role == 4:
            raise AppException(
                ErrorCode.VALIDATION_ERROR, "教练账号走教练端流程，不经此接口创建"
            )
        raise AppException(ErrorCode.VALIDATION_ERROR, "role 仅支持 1超管 / 2运营 / 3商家")
    if role in (1, 2):
        ensure_super(principal)  # 超管专属：非超管一律 1002
        return
    if principal.role in (1, 2):
        return
    raise AppException(ErrorCode.FORBIDDEN)


async def list_accounts(
    session: AsyncSession, principal: AdminPrincipal, page: int, page_size: int
) -> AdminAccountPageData:
    """后台账号分页（仅超管/运营可见，不含密码哈希）。"""
    ensure_manager(principal)
    total = await session.scalar(select(func.count()).select_from(AdminUser))
    rows = (
        (
            await session.execute(
                select(AdminUser)
                .order_by(AdminUser.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    items = [
        AdminAccountOut(
            id=r.id,
            username=r.username,
            role=r.role,
            merchant_id=r.merchant_id,
            created_at=r.created_at,
        )
        for r in rows
    ]
    return AdminAccountPageData(
        items=items,
        page=PageMeta(page=page, page_size=page_size, total=int(total or 0)),
    )


async def create_account(
    session: AsyncSession, principal: AdminPrincipal, payload: AdminAccountIn
) -> AdminAccountOut:
    """创建后台账号（权限分级 + username 唯一 + 商家绑定校验 + 统一弱口令策略）。"""
    _ensure_account_create_allowed(principal, payload.role)

    dup = (
        await session.execute(
            select(AdminUser.id).where(AdminUser.username == payload.username)
        )
    ).scalar_one_or_none()
    if dup is not None:
        raise AppException(ErrorCode.VALIDATION_ERROR, f"账号名已存在：{payload.username}")

    merchant_id: int | None = None
    if payload.role == 3:
        if payload.merchant_id is None:
            raise AppException(ErrorCode.VALIDATION_ERROR, "商家账号必须绑定商家（merchant_id）")
        merchant = (
            await session.execute(select(Merchant).where(Merchant.id == payload.merchant_id))
        ).scalar_one_or_none()
        if merchant is None:
            raise AppException(ErrorCode.VALIDATION_ERROR, "绑定的商家不存在")
        merchant_id = payload.merchant_id
    elif payload.merchant_id is not None:
        raise AppException(ErrorCode.VALIDATION_ERROR, "仅商家账号可绑定 merchant_id")

    weak = reject_weak_password(payload.password)
    if weak:
        raise AppException(ErrorCode.VALIDATION_ERROR, f"密码不合格：{weak}")

    admin = AdminUser(
        username=payload.username,
        password_hash=hash_password(payload.password),
        role=payload.role,
        merchant_id=merchant_id,
    )
    session.add(admin)
    try:
        await session.commit()
    except IntegrityError:
        # 并发同名建号：上面的 dup select 与 insert 之间无锁，最终靠 DB UNIQUE 兜底。
        # 不转成 500，按参数校验错误返回 2001（AGENTS §7.2 错误码映射）。
        await session.rollback()
        raise AppException(
            ErrorCode.VALIDATION_ERROR, f"账号名已存在：{payload.username}"
        ) from None
    await session.refresh(admin)
    return AdminAccountOut(
        id=admin.id,
        username=admin.username,
        role=admin.role,
        merchant_id=admin.merchant_id,
        created_at=admin.created_at,
    )


async def reset_admin_password(
    session: AsyncSession,
    principal: AdminPrincipal,
    account_id: int,
    payload: AdminPasswordResetIn,
) -> AdminAccountOut:
    """重置密码：超管重置任意账号；运营仅可重置商家账号（role=3）。"""
    ensure_manager(principal)
    admin = (
        await session.execute(select(AdminUser).where(AdminUser.id == account_id))
    ).scalar_one_or_none()
    if admin is None:
        raise AppException(ErrorCode.NOT_FOUND, "账号不存在")
    if principal.role == 2 and admin.role != 3:
        raise AppException(ErrorCode.FORBIDDEN, "运营仅可重置商家账号密码")

    weak = reject_weak_password(payload.new_password)
    if weak:
        raise AppException(ErrorCode.VALIDATION_ERROR, f"密码不合格：{weak}")

    admin.password_hash = hash_password(payload.new_password)
    await session.commit()
    return AdminAccountOut(
        id=admin.id,
        username=admin.username,
        role=admin.role,
        merchant_id=admin.merchant_id,
        created_at=admin.created_at,
    )


# ---- 商家审核 ----


async def _geo_coords(session: AsyncSession, merchant_ids: list[int]) -> dict[int, tuple]:
    """批量反解商家坐标（ST_Y=纬度 / ST_X=经度，N-7：geo 空间列存储，出参仍 lat/lng）。"""
    if not merchant_ids:
        return {}
    rows = (
        await session.execute(
            select(Merchant.id, func.ST_Y(Merchant.geo), func.ST_X(Merchant.geo)).where(
                Merchant.id.in_(merchant_ids)
            )
        )
    ).all()
    return {mid: (glat, glng) for mid, glat, glng in rows}


def _merchant_out(
    m: Merchant,
    audit_reason: str | None = None,
    *,
    lat: float | None = None,
    lng: float | None = None,
) -> AdminMerchantOut:
    return AdminMerchantOut(
        id=m.id,
        name=m.name,
        category=m.category,
        address=m.address or "",  # 契约 required，模型可空 -> 空串
        phone=m.phone,
        lat=lat,
        lng=lng,
        rating=float(m.rating),
        cover_url=None,
        status=m.status,
        audit_status=m.audit_status,
        audit_reason=audit_reason,
        owner_user_id=m.owner_user_id,
        created_at=m.created_at,
    )


async def list_merchants(
    session: AsyncSession,
    principal: AdminPrincipal,
    audit_status: int | None,
    page: int,
    page_size: int,
) -> AdminMerchantPageData:
    """商家分页（audit_status 过滤）；【假设】商家角色仅见本商家。"""
    conds = []
    if audit_status is not None:
        conds.append(Merchant.audit_status == audit_status)
    if principal.role == 3:
        conds.append(Merchant.id == principal.merchant_id)
    total = await session.scalar(select(func.count()).select_from(Merchant).where(*conds))
    rows = (
        (
            await session.execute(
                select(Merchant)
                .where(*conds)
                .order_by(Merchant.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    geo_map = await _geo_coords(session, [m.id for m in rows])
    items = []
    for m in rows:
        lat, lng = geo_map.get(m.id, (None, None))
        items.append(_merchant_out(m, lat=lat, lng=lng))
    return AdminMerchantPageData(
        items=items,
        page=PageMeta(page=page, page_size=page_size, total=int(total or 0)),
    )


async def audit_merchant(
    session: AsyncSession, principal: AdminPrincipal, merchant_id: int, payload: AdminAuditIn
) -> AdminMerchantOut:
    """入驻审核：1 通过 / 2 驳回（驳回时回显 reason）。仅 role 1/2。"""
    ensure_manager(principal)
    merchant = (
        await session.execute(select(Merchant).where(Merchant.id == merchant_id))
    ).scalar_one_or_none()
    if merchant is None:
        raise AppException(ErrorCode.NOT_FOUND, "商家不存在")
    merchant.audit_status = payload.audit_status
    reason = payload.reason if payload.audit_status == 2 else None
    await session.commit()
    geo_map = await _geo_coords(session, [merchant.id])
    lat, lng = geo_map.get(merchant.id, (None, None))
    return _merchant_out(merchant, audit_reason=reason, lat=lat, lng=lng)


# ---- 商家选品定价 ----


def _sku_out(sku: MerchantSku, merchant: Merchant, catalog: SkuCatalog) -> AdminMerchantSkuData:
    return AdminMerchantSkuData(
        id=sku.id,
        merchant_id=sku.merchant_id,
        merchant_name=merchant.name if merchant else None,
        catalog_id=sku.catalog_id,
        catalog_code=catalog.code,
        catalog_name=catalog.name,
        price=float(sku.price),
        min_price=float(catalog.min_price),
        max_price=float(catalog.max_price),
        stock=sku.stock,
        status=sku.status,
        updated_at=None,
    )


async def upsert_merchant_sku(
    session: AsyncSession, principal: AdminPrincipal, payload: AdminMerchantSkuIn
) -> AdminMerchantSkuData:
    """选品定价 upsert：(merchant_id, catalog_id) 存在则更新，否则插入。

    价格越出目录 [min_price, max_price] -> 2001/400（业务规则拒绝，HTTP 400；code 仍 2001）。
    并发安全：PG ON CONFLICT（uk_ms 唯一索引）原子 upsert，不再撞 uk_ms 报 500。
    """
    ensure_scope(principal, payload.merchant_id)
    merchant = (
        await session.execute(select(Merchant).where(Merchant.id == payload.merchant_id))
    ).scalar_one_or_none()
    if merchant is None:
        raise AppException(ErrorCode.NOT_FOUND, "商家不存在")
    catalog = (
        await session.execute(select(SkuCatalog).where(SkuCatalog.id == payload.catalog_id))
    ).scalar_one_or_none()
    if catalog is None:
        raise AppException(ErrorCode.NOT_FOUND, "目录 SKU 不存在")
    if not (float(catalog.min_price) <= payload.price <= float(catalog.max_price)):
        raise AppException(
            ErrorCode.VALIDATION_ERROR,
            f"价格超出目录区间 ¥{catalog.min_price:g}-¥{catalog.max_price:g}",
            http_status=400,  # 业务规则拒绝：code 仍 2001，HTTP 覆盖为 400
        )
    stmt = pg_insert(MerchantSku).values(
        merchant_id=payload.merchant_id,
        catalog_id=payload.catalog_id,
        price=payload.price,
        stock=payload.stock,
        status=payload.status,
    )
    # 【调整】DB 中 uk_ms 为唯一索引（非 CONSTRAINT），冲突目标用 index_elements 等价实现
    stmt = stmt.on_conflict_do_update(
        index_elements=[MerchantSku.merchant_id, MerchantSku.catalog_id],
        set_={"price": payload.price, "stock": payload.stock, "status": payload.status},
    )
    await session.execute(stmt)
    await session.commit()
    sku = (
        await session.execute(
            select(MerchantSku).where(
                MerchantSku.merchant_id == payload.merchant_id,
                MerchantSku.catalog_id == payload.catalog_id,
            )
        )
    ).scalar_one()
    return _sku_out(sku, merchant, catalog)


async def set_sku_status(
    session: AsyncSession, principal: AdminPrincipal, sku_id: int, payload: AdminSkuStatusIn
) -> AdminMerchantSkuData:
    """商家 SKU 上下架；不存在 3001，商家角色仅限本商家 SKU（1002）。"""
    sku = (
        await session.execute(select(MerchantSku).where(MerchantSku.id == sku_id))
    ).scalar_one_or_none()
    if sku is None:
        raise AppException(ErrorCode.NOT_FOUND, "商家 SKU 不存在")
    ensure_scope(principal, sku.merchant_id)
    sku.status = payload.status
    merchant = (
        await session.execute(select(Merchant).where(Merchant.id == sku.merchant_id))
    ).scalar_one_or_none()
    catalog = (
        await session.execute(select(SkuCatalog).where(SkuCatalog.id == sku.catalog_id))
    ).scalar_one_or_none()
    if catalog is None:  # 【假设】upsert 必带 catalog_id，目录被清视为资源不存在
        raise AppException(ErrorCode.NOT_FOUND, "目录 SKU 不存在")
    await session.commit()
    return _sku_out(sku, merchant, catalog)


# ---- 标准目录维护（F-05：平台运营维护，商家只选不建）----


def _catalog_out(c: SkuCatalog) -> CatalogItem:
    return CatalogItem.model_validate(c)


async def create_sku_catalog(
    session: AsyncSession, principal: AdminPrincipal, payload: AdminSkuCatalogIn
) -> CatalogItem:
    """新建标准目录项；仅超管/运营（role 1/2）。code 重名 -> 2001/422。"""
    ensure_manager(principal)
    dup = await session.scalar(select(SkuCatalog.id).where(SkuCatalog.code == payload.code))
    if dup is not None:
        raise AppException(ErrorCode.VALIDATION_ERROR, f"目录编码 {payload.code} 已存在")
    catalog = SkuCatalog(
        code=payload.code,
        name=payload.name,
        category=payload.category,
        calories_low=payload.calories_low,
        calories_high=payload.calories_high,
        base_price=payload.base_price,
        min_price=payload.min_price,
        max_price=payload.max_price,
        unit=payload.unit,
    )
    session.add(catalog)
    await session.commit()
    await session.refresh(catalog)
    return _catalog_out(catalog)


async def update_sku_catalog(
    session: AsyncSession, principal: AdminPrincipal, catalog_id: int, payload: AdminSkuCatalogIn
) -> CatalogItem:
    """编辑标准目录项；仅超管/运营。不存在 3001/404，code 与其它项重名 2001/422。"""
    ensure_manager(principal)
    catalog = (
        await session.execute(select(SkuCatalog).where(SkuCatalog.id == catalog_id))
    ).scalar_one_or_none()
    if catalog is None:
        raise AppException(ErrorCode.NOT_FOUND, "目录 SKU 不存在")
    dup = await session.scalar(
        select(SkuCatalog.id).where(
            SkuCatalog.code == payload.code, SkuCatalog.id != catalog_id
        )
    )
    if dup is not None:
        raise AppException(ErrorCode.VALIDATION_ERROR, f"目录编码 {payload.code} 已存在")
    catalog.code = payload.code
    catalog.name = payload.name
    catalog.category = payload.category
    catalog.calories_low = payload.calories_low
    catalog.calories_high = payload.calories_high
    catalog.base_price = payload.base_price
    catalog.min_price = payload.min_price
    catalog.max_price = payload.max_price
    catalog.unit = payload.unit
    await session.commit()
    await session.refresh(catalog)
    return _catalog_out(catalog)


# ---- 券池 ----


def _pool_out(p: CouponPool) -> AdminCouponPoolOut:
    return AdminCouponPoolOut(
        id=p.id,
        name=p.name,
        type=p.type,
        scope=p.scope,
        amount=float(p.amount),
        discount_rate=float(p.discount_rate) if p.discount_rate is not None else None,
        min_spend=float(p.min_spend),
        merchant_id=p.merchant_id,
        total_count=p.total_count,
        granted_count=p.granted_count,
        valid_from=p.valid_from,
        valid_to=p.valid_to,
        created_at=p.created_at,
    )


async def list_coupon_pools(
    session: AsyncSession, principal: AdminPrincipal, page: int, page_size: int
) -> AdminCouponPoolPageData:
    """券池分页（platform 级视图）；仅超管/运营可读（与 create 同权限口径）。"""
    ensure_manager(principal)
    total = await session.scalar(select(func.count()).select_from(CouponPool))
    rows = (
        (
            await session.execute(
                select(CouponPool)
                .order_by(CouponPool.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return AdminCouponPoolPageData(
        items=[_pool_out(p) for p in rows],
        page=PageMeta(page=page, page_size=page_size, total=int(total or 0)),
    )


async def create_coupon_pool(
    session: AsyncSession, principal: AdminPrincipal, payload: AdminCouponPoolIn
) -> AdminCouponPoolOut:
    """创建券池（发放唯一源头）。type=2 折扣券必须带 discount_rate；(0,1]。

    type 1/3/4 需 amount > 0【假设】。校验失败统一 2001/422。
    """
    ensure_manager(principal)
    if payload.type == 2:
        if payload.discount_rate is None:
            raise AppException(ErrorCode.VALIDATION_ERROR, "折扣券必须提供 discount_rate")
    elif payload.amount <= 0:
        raise AppException(ErrorCode.VALIDATION_ERROR, "满减/免费/体验券 amount 必须大于 0")
    pool = CouponPool(
        name=payload.name,
        type=payload.type,
        scope=payload.scope,
        amount=payload.amount,
        discount_rate=payload.discount_rate,
        min_spend=payload.min_spend,
        merchant_id=payload.merchant_id,
        total_count=payload.total_count,
        valid_from=payload.valid_from,
        valid_to=payload.valid_to,
    )
    session.add(pool)
    await session.commit()
    return _pool_out(pool)


async def _gen_coupon_codes(session: AsyncSession, count: int) -> list[str]:
    """生成 count 个不冲突的券码：CP + 8 位大写字母数字，冲突重试。"""
    codes: set[str] = set()
    for _ in range(_CODE_ATTEMPTS):
        candidates = {
            f"CP{''.join(secrets.choice(_ALNUM) for _ in range(8))}" for _ in range(count)
        }
        existed = set(
            (await session.execute(select(Coupon.code).where(Coupon.code.in_(candidates))))
            .scalars()
        )
        codes |= candidates - existed
        if len(codes) >= count:
            break
    if len(codes) < count:
        raise AppException(ErrorCode.SERVER_ERROR, "券码生成失败，请重试")
    return list(codes)[:count]


async def grant_coupons(
    session: AsyncSession, principal: AdminPrincipal, payload: AdminGrantIn
) -> AdminGrantData:
    """从券池向用户发放券：FOR UPDATE 锁池，余量不足 4001/409。

    Phase 2 并发教训：池更新与券插入同一事务（flush 不拆事务，末尾单次 commit）。
    """
    ensure_manager(principal)
    pool = (
        await session.execute(
            select(CouponPool).where(CouponPool.id == payload.pool_id).with_for_update()
        )
    ).scalar_one_or_none()
    if pool is None:
        raise AppException(ErrorCode.NOT_FOUND, "券池不存在")
    user = (
        await session.execute(select(User).where(User.id == payload.user_id))
    ).scalar_one_or_none()
    if user is None:
        raise AppException(ErrorCode.NOT_FOUND, "用户不存在")
    # 余量校验（total_count=-1 不限量【假设】）
    if pool.total_count != -1 and pool.granted_count + payload.count > pool.total_count:
        raise AppException(ErrorCode.QUOTA_EXCEEDED, "券池余量不足")

    codes = await _gen_coupon_codes(session, payload.count)
    coupons = [
        Coupon(
            pool_id=pool.id,
            code=code,
            type=pool.type,
            scope=pool.scope,
            amount=pool.amount,
            discount_rate=pool.discount_rate,
            min_spend=pool.min_spend,
            merchant_id=pool.merchant_id,
            sponsor=pool.sponsor,
            obtain_way=3,  # 【假设】平台补贴通道
            obtain_user_id=payload.user_id,
            status=1,
            valid_from=pool.valid_from,
            valid_to=pool.valid_to,
        )
        for code in codes
    ]
    session.add_all(coupons)
    pool.granted_count += payload.count
    await session.flush()  # 池更新与券插入同事务，锁保持至 commit
    await session.commit()
    return AdminGrantData(
        granted_count=pool.granted_count,
        pool_id=pool.id,
        user_id=payload.user_id,
        coupons=[CouponOut.model_validate(c) for c in coupons],
    )


# ---- 订单监控 ----


async def list_orders(
    session: AsyncSession,
    principal: AdminPrincipal,
    status: int | None,
    merchant_id: int | None,
    page: int,
    page_size: int,
) -> OrderPageData:
    """订单全量分页；商家角色强制注入本商家过滤（忽略查询参数）。"""
    if principal.role == 3:
        merchant_id = principal.merchant_id
    conds = []
    if status is not None:
        conds.append(Order.status == status)
    if merchant_id is not None:
        conds.append(Order.merchant_id == merchant_id)
    total = await session.scalar(select(func.count()).select_from(Order).where(*conds))
    rows = (
        (
            await session.execute(
                select(Order)
                .where(*conds)
                .order_by(Order.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    names: dict[int, str] = {}
    mids = {o.merchant_id for o in rows if o.merchant_id is not None}
    if mids:
        pairs = (
            await session.execute(select(Merchant.id, Merchant.name).where(Merchant.id.in_(mids)))
        ).all()
        names = {pid: pname for pid, pname in pairs}
    items = [
        OrderBrief(
            id=o.id,
            order_no=o.order_no,
            merchant_id=o.merchant_id or 0,  # 【假设】契约 required，模型可空 -> 0
            merchant_name=names.get(o.merchant_id),
            total_amount=float(o.total_amount),
            discount_amount=float(o.discount_amount),
            pay_amount=float(o.pay_amount),
            status=o.status,
            redeem_code=o.redeem_code,
            expire_at=o.expire_at,
            created_at=o.created_at,
        )
        for o in rows
    ]
    return OrderPageData(
        items=items, page=PageMeta(page=page, page_size=page_size, total=int(total or 0))
    )


# ---- 运营看板（IS-008: 真实聚合查询）----


async def get_dashboard(session: AsyncSession, target_date: date | None = None) -> dict:
    """IS-008: 运营看板聚合查询。

    - GMV: 仅统计已支付待核销(2)和已完成(3)的订单，排除已取消(4)和已退款(5)
    - active_users: 当日有饮食记录或运动记录的去重用户数
    - 时间边界: 使用 UTC+8 时区感知的 datetime，与 DB 的 TIMESTAMPTZ 对齐
    """
    if target_date is None:
        target_date = datetime.now(_TZ).date()

    # 构造当日时间边界（UTC+8）
    start_of_day = datetime.combine(target_date, time.min, tzinfo=_TZ)
    end_of_day = datetime.combine(target_date, time.max, tzinfo=_TZ)

    # 累计用户数
    user_count = await session.scalar(select(func.count()).select_from(User)) or 0

    # 今日活跃用户（有饮食记录或运动记录）
    # MealRecord 使用 record_date (Date 类型)，SportRecord 使用 record_at (TIMESTAMPTZ)
    meal_user_ids = await session.scalars(
        select(MealRecord.user_id).where(
            MealRecord.record_date == target_date,
            MealRecord.user_id.isnot(None),
        )
    )
    sport_user_ids = await session.scalars(
        select(SportRecord.user_id).where(
            SportRecord.record_at >= start_of_day,
            SportRecord.record_at <= end_of_day,
            SportRecord.user_id.isnot(None),
        )
    )
    active_users_today = len(set(meal_user_ids.all()) | set(sport_user_ids.all()))

    # 今日饮食记录数
    meal_records_today = await session.scalar(
        select(func.count()).select_from(MealRecord).where(
            MealRecord.record_date == target_date
        )
    ) or 0

    # 今日订单数
    orders_today = await session.scalar(
        select(func.count()).select_from(Order).where(
            Order.created_at >= start_of_day,
            Order.created_at <= end_of_day,
        )
    ) or 0

    # 今日 GMV（已支付待核销 + 已完成，排除已取消和已退款）
    gmv_today = await session.scalar(
        select(func.coalesce(func.sum(Order.pay_amount), 0.0)).where(
            Order.status.in_([2, 3]),  # 已支付待核销 + 已完成
            Order.created_at >= start_of_day,
            Order.created_at <= end_of_day,
        )
    ) or 0.0

    # 今日 AI 调用次数（仅统计用户发起的对话）
    ai_calls_today = await session.scalar(
        select(func.count()).select_from(AiDialog).where(
            AiDialog.created_at >= start_of_day,
            AiDialog.created_at <= end_of_day,
            AiDialog.role == "user",
        )
    ) or 0

    return {
        "date": target_date,
        "user_count": user_count,
        "active_users_today": active_users_today,
        "meal_records_today": meal_records_today,
        "orders_today": orders_today,
        "gmv_today": float(gmv_today),
        "ai_calls_today": ai_calls_today,
    }


# ---- Phase 4 ADM：内容审核队列 ----


def _audit_item(r: Review, nickname: str | None) -> AdminAuditItem:
    return AdminAuditItem(
        id=r.id,
        target_type=r.target_type,
        target_id=r.target_id,
        user_id=r.user_id,
        nickname=nickname,
        content_snapshot=r.content_snapshot,
        sec_check_result=r.sec_check_result,
        status=r.status,
        reject_reason=r.reject_reason,
        reviewer_id=r.reviewer_id,
        reviewed_at=r.reviewed_at,
        created_at=r.created_at,
    )


async def list_audit(
    session: AsyncSession,
    principal: AdminPrincipal,
    status: int | None,
    page: int,
    page_size: int,
) -> AdminAuditPageData:
    """审核队列分页（status 过滤：0待审 1通过 2驳回），仅超管/运营。"""
    ensure_manager(principal)
    conds = []
    if status is not None:
        conds.append(Review.status == status)
    total = await session.scalar(select(func.count()).select_from(Review).where(*conds))
    rows = (
        (
            await session.execute(
                select(Review)
                .where(*conds)
                .order_by(Review.created_at.desc(), Review.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    nicknames: dict[int, str] = {}
    uids = {r.user_id for r in rows if r.user_id}
    if uids:
        pairs = (
            await session.execute(select(User.id, User.nickname).where(User.id.in_(uids)))
        ).all()
        nicknames = {uid: name for uid, name in pairs}
    return AdminAuditPageData(
        items=[_audit_item(r, nicknames.get(r.user_id)) for r in rows],
        page=PageMeta(page=page, page_size=page_size, total=int(total or 0)),
    )


async def review_audit(
    session: AsyncSession, principal: AdminPrincipal, review_id: int, payload: AdminReviewIn
) -> AdminReviewData:
    """处理审核：1 通过 / 2 驳回；同步回写目标内容 audit_status（动态/评论）。"""
    ensure_manager(principal)
    review = (
        await session.execute(select(Review).where(Review.id == review_id))
    ).scalar_one_or_none()
    if review is None:
        raise AppException(ErrorCode.NOT_FOUND, "审核记录不存在")
    # 内容侧 audit_status：1通过 2驳回
    audit_status = 1 if payload.status == 1 else 2
    if review.target_type == 1:
        await session.execute(
            update(CommunityPost)
            .where(CommunityPost.id == review.target_id)
            .values(audit_status=audit_status)
        )
    elif review.target_type == 2:
        comment = (
            await session.execute(
                select(CommunityComment).where(CommunityComment.id == review.target_id)
            )
        ).scalar_one_or_none()
        if comment is not None:
            comment.audit_status = audit_status
            await session.flush()
            # 权威重算：comment_count = 该帖可见评论数（audit_status=1），
            # 与评论列表可见口径一致；反复审核/通过↔驳回切换天然幂等收敛。
            visible_count = (
                select(func.count())
                .select_from(CommunityComment)
                .where(
                    CommunityComment.post_id == comment.post_id,
                    CommunityComment.audit_status == 1,
                )
            )
            await session.execute(
                update(CommunityPost)
                .where(CommunityPost.id == comment.post_id)
                .values(comment_count=visible_count.scalar_subquery())
            )
    review.status = payload.status
    review.reject_reason = payload.reason if payload.status == 2 else None
    review.reviewer_id = principal.id
    review.reviewed_at = datetime.now(_TZ)
    await session.commit()
    return AdminReviewData(
        id=review.id,
        target_type=review.target_type,
        target_id=review.target_id,
        status=review.status,
        reject_reason=review.reject_reason,
        reviewed_at=review.reviewed_at,
    )
