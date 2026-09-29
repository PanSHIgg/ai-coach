"""订单域服务（Phase 3 BE6）：下单 → 支付 → 回调 → 核销 → 列表 全闭环。

金额口径：服务端按 merchant_sku.price 重算，绝不信任前端；
DB 层 numeric(10,2) + CHECK(pay_amount=total-discount)，Python 侧统一 round(2)。

并发安全（Phase 2 教训，ai_service.ensure_benefit）：关键行读用 FOR UPDATE，
全流程只 flush/改属性，函数末尾一次 commit 原子提交，不提前放锁。

状态机（冻结枚举）：1待支付 → 2已支付待核销 → 3已完成；
超时/取消 1→4（同时释放券）；退款 2→5 已退款（幂等，仅状态流转）。
"""

import hashlib
import hmac
import secrets
import string
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import AppException
from app.models import Coupon, Merchant, MerchantSku, Order, OrderItem, RedeemLog, SkuCatalog
from app.schemas.common import ErrorCode
from app.services import wechat_pay

ORDER_EXPIRE_MINUTES = 15  # 待支付有效期
_GYM_CATEGORY = "健身房"  # 【假设】scope 1/2 以 merchant.category == '健身房' 划分


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# 签名（pay_params 伪造 + 回调验签共用 HMAC-SHA256，key=JWT_SECRET）
# ---------------------------------------------------------------------------


def notify_sign(order_no: str, amount: float, secret: str | None = None) -> str:
    """【假设】回调签名 = HMAC-SHA256(JWT_SECRET, f"{order_no}|{amount:.2f}")。"""
    key = (secret if secret is not None else get_settings().JWT_SECRET).encode()
    return hmac.new(key, f"{order_no}|{amount:.2f}".encode(), hashlib.sha256).hexdigest()


def pay_sign(order_no: str, ts: str, nonce: str) -> str:
    """【假设】mock 支付参数 paySign，同为 HMAC 伪造，仅供前端透传。"""
    key = get_settings().JWT_SECRET.encode()
    return hmac.new(key, f"pay|{order_no}|{ts}|{nonce}".encode(), hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------


async def _gen_order_no(session: AsyncSession) -> str:
    """DD + yyyyMMdd + 8 位随机大写 hex（secrets）；唯一约束兜底极端并发。"""
    return "DD" + _now().strftime("%Y%m%d") + secrets.token_hex(4).upper()


async def _gen_redeem_code(session: AsyncSession) -> str:
    """RD + 10 位随机大写字母/数字，查重冲突重试（唯一约束兜底）。"""
    alphabet = string.ascii_uppercase + string.digits
    for _ in range(5):
        code = "RD" + "".join(secrets.choice(alphabet) for _ in range(10))
        if await session.scalar(select(Order.id).where(Order.redeem_code == code)) is None:
            return code
    raise AppException(ErrorCode.SERVER_ERROR, "核销码生成失败")


async def _release_coupon(session: AsyncSession, coupon_id: int | None) -> None:
    """订单取消时释放绑定券：2已用 → 1未用，解绑订单并清 used_at。"""
    if coupon_id is None:
        return
    coupon = await session.get(Coupon, coupon_id)
    if coupon is not None and coupon.status == 2:
        coupon.status = 1
        coupon.order_id = None
        coupon.used_at = None


async def _cancel_order(session: AsyncSession, order: Order) -> None:
    """超时取消：1待支付 → 4已取消 + 释放券。"""
    order.status = 4
    await _release_coupon(session, order.coupon_id)


async def _log_redeem(
    session: AsyncSession, order: Order, merchant_id: int, result: int, fail_reason: str | None
) -> None:
    """核销留痕：成功/失败全记 redeem_log（模型注释约定）。"""
    session.add(
        RedeemLog(
            order_id=order.id,
            merchant_id=merchant_id,
            result=result,
            fail_reason=fail_reason,
        )
    )


# ---------------------------------------------------------------------------
# 下单
# ---------------------------------------------------------------------------


def _validate_coupon(coupon: Coupon, user_id: int, merchant: Merchant, total: float) -> None:
    """券可用性：归属/未用/有效期/门槛/scope/指定商家，任一不满足 → 5002。"""
    now = _now()
    scope_ok = (
        coupon.scope in (3, 4)
        or (coupon.scope == 1 and merchant.category != _GYM_CATEGORY)
        or (coupon.scope == 2 and merchant.category == _GYM_CATEGORY)
    )
    usable = (
        coupon.obtain_user_id == user_id
        and coupon.status == 1
        and (coupon.valid_from is None or coupon.valid_from <= now)
        and (coupon.valid_to is None or coupon.valid_to >= now)
        and float(coupon.min_spend) <= total
        and scope_ok
        and (coupon.merchant_id is None or coupon.merchant_id == merchant.id)
    )
    if not usable:
        raise AppException(ErrorCode.COUPON_UNAVAILABLE)


def _coupon_discount(coupon: Coupon, lines: list[tuple[MerchantSku, int]], total: float) -> float:
    """按券类型算折扣额：1满减/4体验=amount，2折扣=total*(1-rate)，3免费=最高单价【假设】。"""
    if coupon.type in (1, 4):
        return float(coupon.amount)
    if coupon.type == 2:
        return total * (1 - float(coupon.discount_rate or 0))
    return max(float(sku.price) for sku, _, _ in lines)  # type 3 免费


async def create_order(
    session: AsyncSession, user_id: int, payload, _retried: bool = False
) -> Order:
    """创建订单：商家/SKU/券校验 + 服务端计价 + 写单绑券，单事务原子提交。

    订单号撞唯一约束（概率极低）：回滚后整体重试 1 次。
    """
    merchant = (
        await session.execute(select(Merchant).where(Merchant.id == payload.merchant_id))
    ).scalar_one_or_none()
    if merchant is None or merchant.audit_status != 1:  # 【假设】未过审视同不存在
        raise AppException(ErrorCode.NOT_FOUND, "商家不存在")
    if merchant.status != 1:
        raise AppException(ErrorCode.MERCHANT_CLOSED)

    # 合并重复 sku 行后逐个加锁校验（防并发下库存读旧值）
    qty_by_sku: dict[int, int] = {}
    for it in payload.items:
        qty_by_sku[it.sku_id] = qty_by_sku.get(it.sku_id, 0) + it.qty

    lines: list[tuple[MerchantSku, int, str]] = []
    total = 0.0
    for sku_id, qty in qty_by_sku.items():
        sku = (
            await session.execute(
                select(MerchantSku).where(MerchantSku.id == sku_id).with_for_update()
            )
        ).scalar_one_or_none()
        if sku is None or sku.merchant_id != payload.merchant_id:
            raise AppException(ErrorCode.NOT_FOUND, "SKU 不存在")
        if sku.status != 1:  # 【假设】下架 → 2001
            raise AppException(ErrorCode.VALIDATION_ERROR, "SKU 已下架")
        if sku.stock != -1 and sku.stock < qty:  # 【假设】库存不足 → 2001
            raise AppException(ErrorCode.VALIDATION_ERROR, "库存不足")
        catalog = await session.get(SkuCatalog, sku.catalog_id) if sku.catalog_id else None
        name = catalog.name if catalog else f"SKU-{sku.id}"
        total += float(sku.price) * qty
        lines.append((sku, qty, name))
    total = round(total, 2)

    coupon: Coupon | None = None
    discount = 0.0
    if payload.coupon_id is not None:
        coupon = (
            await session.execute(
                select(Coupon).where(Coupon.id == payload.coupon_id).with_for_update()
            )
        ).scalar_one_or_none()
        if coupon is None:
            raise AppException(ErrorCode.NOT_FOUND, "券不存在")
        _validate_coupon(coupon, user_id, merchant, total)
        discount = round(_coupon_discount(coupon, lines, total), 2)
    pay = round(total - discount, 2)
    if pay < 0:  # 【假设】券额超总价 → 2001，不静默钳 0
        raise AppException(ErrorCode.VALIDATION_ERROR, "支付金额不能为负")

    order = Order(
        order_no=await _gen_order_no(session),
        user_id=user_id,
        merchant_id=payload.merchant_id,
        total_amount=total,
        discount_amount=discount,
        pay_amount=pay,
        coupon_id=coupon.id if coupon is not None else None,
        status=1,
        expire_at=_now() + timedelta(minutes=ORDER_EXPIRE_MINUTES),
    )
    session.add(order)
    try:
        await session.flush()  # 取 order.id；不 commit，保持行锁到事务末尾
        for sku, qty, name in lines:
            session.add(
                OrderItem(
                    order_id=order.id,
                    sku_id=sku.id,
                    sku_name_snapshot=name,
                    unit_price=float(sku.price),
                    quantity=qty,
                    subtotal=round(float(sku.price) * qty, 2),
                )
            )
        if coupon is not None:  # 绑券占位：2已用 + 回链订单（used_at 待支付成功再写）
            coupon.status = 2
            coupon.order_id = order.id
        await session.commit()
    except IntegrityError:
        # 订单号唯一约束冲突（极端并发撞号）：回滚后整单重试 1 次
        await session.rollback()
        if _retried:
            raise AppException(ErrorCode.SERVER_ERROR, "订单号生成冲突，请重试")
        return await create_order(session, user_id, payload, _retried=True)
    await session.refresh(order)  # 补齐 created_at 等 server_default 列
    return order


# ---------------------------------------------------------------------------
# 支付（预下单 + 回调）
# ---------------------------------------------------------------------------


async def _get_user_order(session: AsyncSession, order_id: int, user_id: int) -> Order:
    order = (
        await session.execute(
            select(Order).where(Order.id == order_id, Order.user_id == user_id)
        )
    ).scalar_one_or_none()
    if order is None:  # 不存在/越权统一 3001（行级隔离约定）
        raise AppException(ErrorCode.NOT_FOUND, "订单不存在")
    return order


async def _mark_paid(session: AsyncSession, order: Order) -> None:
    """支付成功推进（notify 与 mock pay 收敛到同一实现）：
    1→2 + pay_at + 核销码 + 券 used_at + 扣库存（含 P0-2 余量校验，不足抛 2001 整体回滚）。
    """
    order.status = 2
    order.pay_at = _now()
    order.redeem_code = await _gen_redeem_code(session)
    if order.coupon_id is not None:
        coupon = await session.get(Coupon, order.coupon_id)
        if coupon is not None:
            coupon.used_at = _now()
    items = (
        await session.execute(select(OrderItem).where(OrderItem.order_id == order.id))
    ).scalars().all()
    for it in items:
        if it.sku_id is None or it.quantity <= 0:
            continue
        sku = (
            await session.execute(
                select(MerchantSku).where(MerchantSku.id == it.sku_id).with_for_update()
            )
        ).scalar_one_or_none()
        if sku is not None and sku.stock != -1:  # -1 不限量不扣
            if sku.stock < it.quantity:  # 余量不足 → 抛出使整个事务回滚，订单停留待支付
                raise AppException(ErrorCode.VALIDATION_ERROR, "库存不足")
            sku.stock -= it.quantity


def _mock_pay_params(order: Order) -> dict[str, Any]:
    """沙箱拉起参数：paySign 用 HMAC 伪造（演示/测试专用，生产禁用）。"""
    ts = str(int(time.time()))
    nonce = secrets.token_hex(8)
    return {
        "timeStamp": ts,
        "nonceStr": nonce,
        "package": f"prepay_id=mock_{order.order_no}",
        "paySign": pay_sign(order.order_no, ts, nonce),
        "mock": True,  # 沙箱标记：前端/测试可识别
    }


async def pay_order(
    session: AsyncSession, user_id: int, order_id: int, settings: Settings | None = None
) -> tuple[Order, dict[str, Any]]:
    """预下单：校验归属+待支付+未过期；返回 (订单, 拉起支付参数)。

    PAY_MOCK_MODE（沙箱支付，演示默认开）：直接执行支付成功推进（与 notify 同一 _mark_paid），
    返回带 mock 标记的本地签名参数；
    为假（真实接入）：调用 wechat_pay.prepare_payment 预下单——已配置走真实统一下单，
    未配置则明确降级返回 degraded 占位参数；订单保持待支付，等 notify 推进。
    """
    order = await _get_user_order(session, order_id, user_id)
    if order.status == 1 and order.expire_at is not None and order.expire_at < _now():
        await _cancel_order(session, order)
        await session.commit()
        raise AppException(ErrorCode.ORDER_TIMEOUT)
    if order.status != 1:  # 【假设】非待支付再拉起支付 → 2001
        raise AppException(ErrorCode.VALIDATION_ERROR, "订单状态不可支付")
    s = settings or get_settings()
    if s.PAY_MOCK_MODE:
        await _mark_paid(session, order)
        await session.commit()
        return order, _mock_pay_params(order)
    prep = await wechat_pay.prepare_payment(order, s)
    return order, prep.pay_params


async def handle_notify(session: AsyncSession, payload: dict[str, Any]) -> dict[str, str]:
    """微信支付回调（无认证）：验签 → 幂等 → 防篡改 → 状态机推进 + 扣库存。"""
    order_no = payload.get("order_no")
    raw_amount = payload.get("amount")
    sign = payload.get("sign")
    if not order_no or raw_amount is None or not sign:
        raise AppException(ErrorCode.VALIDATION_ERROR, "回调参数缺失")
    try:
        amount = float(raw_amount)
    except (TypeError, ValueError) as exc:
        raise AppException(ErrorCode.VALIDATION_ERROR, "回调金额非法") from exc
    if not hmac.compare_digest(notify_sign(str(order_no), amount), str(sign)):
        raise AppException(ErrorCode.VALIDATION_ERROR, "回调验签失败")

    order = (
        await session.execute(
            select(Order).where(Order.order_no == order_no).with_for_update()
        )
    ).scalar_one_or_none()
    if order is None:
        raise AppException(ErrorCode.NOT_FOUND, "订单不存在")
    if order.status == 4:  # 已取消订单收到迟到回调：不再应答成功
        raise AppException(ErrorCode.ORDER_TIMEOUT, "订单已取消")
    if order.status >= 2:  # 幂等：已支付/已完成重复回调直接应答成功
        return {"result": "ok"}
    if order.expire_at is not None and order.expire_at < _now():
        await _cancel_order(session, order)
        await session.commit()
        raise AppException(ErrorCode.ORDER_TIMEOUT)
    if abs(amount - float(order.pay_amount)) > 0.005:  # 防篡改（2 位小数半阈值）
        raise AppException(ErrorCode.VALIDATION_ERROR, "回调金额与订单不符")

    await _mark_paid(session, order)
    await session.commit()
    return {"result": "ok"}


# ---------------------------------------------------------------------------
# 核销
# ---------------------------------------------------------------------------


async def redeem_order(
    session: AsyncSession, order_id: int, code: str, merchant_id: int, user_id: int
) -> Order:
    """商家核销：商家归属校验 → 状态机（2→3）；失败全留痕 redeem_log(result=2)。"""
    merchant = (
        await session.execute(select(Merchant).where(Merchant.id == merchant_id))
    ).scalar_one_or_none()
    if merchant is None:
        raise AppException(ErrorCode.NOT_FOUND, "商家不存在")
    if merchant.owner_user_id is not None and merchant.owner_user_id != user_id:
        # 商家已绑定 owner：仅 owner 本人可核销（owner 体系未建时 owner=NULL 放行）
        raise AppException(ErrorCode.COUPON_UNAVAILABLE, "无该商家核销权限")

    order = (
        await session.execute(select(Order).where(Order.id == order_id).with_for_update())
    ).scalar_one_or_none()
    if order is None:
        raise AppException(ErrorCode.NOT_FOUND, "订单不存在")

    async def _fail(reason: str, err: int) -> AppException:
        await _log_redeem(session, order, merchant_id, 2, reason)
        await session.commit()
        return AppException(err, reason)

    if order.merchant_id != merchant_id:  # 【假设】他人商家核销 → 5002(409)
        raise await _fail("商家与订单不匹配", ErrorCode.COUPON_UNAVAILABLE)
    if order.redeem_code != code:  # 【假设】码不匹配 → 2001
        raise await _fail("核销码不正确", ErrorCode.VALIDATION_ERROR)
    if order.status == 2:
        order.status = 3
        await _log_redeem(session, order, merchant_id, 1, None)
        await session.commit()
        return order
    # 【假设】状态映射：3已完成→5004 已核销；1待支付→5003；4已取消/5已退款→5002
    table = {
        1: ("订单未支付", ErrorCode.ORDER_TIMEOUT),
        3: ("核销码已使用", ErrorCode.REDEEM_CODE_USED),
        4: ("订单已取消", ErrorCode.COUPON_UNAVAILABLE),
        5: ("订单已退款", ErrorCode.COUPON_UNAVAILABLE),
    }
    reason, err = table.get(order.status, ("订单状态不可核销", ErrorCode.VALIDATION_ERROR))
    raise await _fail(reason, err)


# ---------------------------------------------------------------------------
# 退款
# ---------------------------------------------------------------------------


async def refund_order(
    session: AsyncSession, user_id: int, order_id: int, reason: str | None = None
) -> Order:
    """退款：2 已支付待核销 → 5 已退款（幂等：已退款直接返回成功，不重复流转）。

    - 订单不存在 → 3001；非本人订单 → 1002；状态非 2/5 → 2001；
    - `SELECT ... FOR UPDATE` 锁订单行，防并发重复退款；
    - 【假设】退款仅做状态流转 2→5，不回滚库存/券（订单表结构冻结，无退款字段列）。
    """
    order = (
        await session.execute(select(Order).where(Order.id == order_id).with_for_update())
    ).scalar_one_or_none()
    if order is None:
        raise AppException(ErrorCode.NOT_FOUND, "订单不存在")
    if order.user_id != user_id:  # 越权（非本人订单）→ 1002(403)
        raise AppException(ErrorCode.FORBIDDEN, "无权操作该订单")
    if order.status == 5:  # 幂等：已退款重复申请 → 成功且不重复流转
        return order
    if order.status != 2:  # 仅「已支付待核销」可退（1/3/4 → 2001）
        raise AppException(ErrorCode.VALIDATION_ERROR, "订单状态不可退款")
    order.status = 5
    await session.commit()
    return order


# ---------------------------------------------------------------------------
# 列表 + 惰性超时
# ---------------------------------------------------------------------------


async def cancel_expired(session: AsyncSession, user_id: int | None = None) -> int:
    """惰性超时：status=1 且 expire_at<now → 4已取消 + 券释放；返回取消条数。"""
    stmt = select(Order).where(
        Order.status == 1, Order.expire_at.is_not(None), Order.expire_at < _now()
    )
    if user_id is not None:
        stmt = stmt.where(Order.user_id == user_id)
    orders = (await session.execute(stmt.with_for_update())).scalars().all()
    for order in orders:
        await _cancel_order(session, order)
    if orders:
        await session.commit()
    return len(orders)


async def list_orders(
    session: AsyncSession, user_id: int, status: int | None, page: int, page_size: int
) -> tuple[list[Order], int, dict[int, str]]:
    """我的订单分页（created_at DESC），先惰性清超时单；返回(订单, 总数, 商家名表)。"""
    await cancel_expired(session, user_id)
    base = select(Order).where(Order.user_id == user_id)
    count_stmt = select(func.count()).select_from(Order).where(Order.user_id == user_id)
    if status is not None:
        base = base.where(Order.status == status)
        count_stmt = count_stmt.where(Order.status == status)
    total = await session.scalar(count_stmt)
    orders = (
        (
            await session.execute(
                base.order_by(Order.created_at.desc(), Order.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    merchant_ids = {o.merchant_id for o in orders if o.merchant_id is not None}
    names: dict[int, str] = {}
    if merchant_ids:
        rows = (
            await session.execute(select(Merchant).where(Merchant.id.in_(merchant_ids)))
        ).scalars()
        names = {m.id: m.name for m in rows}
    return list(orders), int(total or 0), names
