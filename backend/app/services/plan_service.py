"""平台自营会员订阅付费业务（openapi: /api/plan/*，current.md §2.1 G2）。

路径族刻意避开 `/api/subscription`（已被「提醒订阅」占用，见 notification_service）与
`/api/order`（order 绑定 merchant_id 与核销语义，平台自营无商家），故数据落在 `plan_order`。

金额口径：入参只收 `tier`，`pay_amount` 由服务端按 `PLAN_TIERS` 重算，绝不信任前端。
回调口径：签名/幂等/防篡改完全复用 `order_service.notify_sign` 的
HMAC-SHA256(JWT_SECRET, "{order_no}|{amount:.2f}")，避免两套支付回调签名漂移。

状态机：1待支付 → 2已支付（写权益）/ 3已取消（超时）。

【假设】档位价格与权益额度文档只给了进阶 29 / 高级 59，终身档价格与 AI/教练次数额度
为占位值，集中在本文件 `PLAN_TIERS`，后续运营可配只需改此处。
【假设】到期降级取最简：读取权益时判定（valid_to < now → 按 tier=0 生效），不做落库
批量降级（文档说次日批量，待定时任务落地）。
"""

from __future__ import annotations

import secrets
import string
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import AppException
from app.models import PlanOrder, UserBenefit
from app.schemas.common import ErrorCode
from app.services import wechat_pay
from app.services.order_service import notify_sign

ORDER_STATUS_PENDING = 1  # 1待支付
ORDER_STATUS_PAID = 2  # 2已支付
ORDER_STATUS_CANCELED = 3  # 3已取消
ORDER_EXPIRE_MINUTES = 15  # 待支付有效期（与 order 域一致）
_AMOUNT_EPS = 0.005  # 金额比较阈值（2 位小数半阈值，与 order_service 同）
_ALNUM = string.ascii_uppercase + string.digits

# 档位定义（价格/权益集中在此；金额单位元）
PLAN_TIERS: dict[int, dict[str, Any]] = {
    1: {
        "name": "进阶会员",
        "price": 29.00,
        "valid_days": 30,
        "ai_times": 30,
        "coach_times": 5,
        "description": "扩容 AI 次数 + 每月真人教练问诊额度",
    },
    2: {
        "name": "高级会员",
        "price": 59.00,
        "valid_days": 30,
        "ai_times": 60,
        "coach_times": 15,
        "description": "更高 AI 次数 + 更多真人教练问诊额度",
    },
    3: {
        "name": "终身会员",
        "price": 199.00,  # 【假设】文档未给价
        "valid_days": None,
        "ai_times": 200,
        "coach_times": 60,
        "description": "终身不限期（valid_to 为 NULL）",
    },
}

BASE_AI_TIMES = 10  # 基础档 AI 次数（user_benefit 默认值）
BASE_COACH_TIMES = 0  # 基础档真人教练次数


def _now() -> datetime:
    return datetime.now(UTC)


def _new_order_no() -> str:
    return (
        "PL"
        + _now().strftime("%Y%m%d%H%M%S")
        + "".join(secrets.choice(_ALNUM) for _ in range(6))
    )


# ---------------------------------------------------------------------------
# 档位与权益
# ---------------------------------------------------------------------------


def list_tiers() -> list[dict[str, Any]]:
    """在售档位（价格与权益的唯一来源，服务端重算金额也取自这里）。"""
    return [{"tier": tier, **conf} for tier, conf in PLAN_TIERS.items()]


async def get_benefit(session: AsyncSession, user_id: int) -> dict[str, Any]:
    """当前会员权益；无权益行按基础档返回。

    到期降级【假设】：`valid_to < now` 时按 tier=0 生效（仅读取时判定，不落库），
    `expired` 置 True 供前端提示续费。
    """
    benefit = (
        await session.execute(select(UserBenefit).where(UserBenefit.user_id == user_id))
    ).scalar_one_or_none()
    if benefit is None:
        return {
            "tier": 0,
            "ai_times_left": BASE_AI_TIMES,
            "coach_times_left": BASE_COACH_TIMES,
            "valid_to": None,
            "expired": False,
        }
    valid_to = benefit.valid_to
    expired = valid_to is not None and valid_to < _now()
    return {
        "tier": 0 if expired else int(benefit.tier or 0),
        "ai_times_left": int(benefit.ai_times_left or 0),
        "coach_times_left": int(benefit.coach_times_left or 0),
        "valid_to": valid_to,
        "expired": expired,
    }


async def _grant_benefit(
    session: AsyncSession, user_id: int, tier: int, paid_at: datetime
) -> UserBenefit:
    """支付成功后写权益：tier / ai_times_left / coach_times_left / valid_to。

    valid_to：包月档 = paid_at + valid_days（tier3 终身为 NULL）；同事务内与订单状态流转
    一起提交，避免「订单已支付但权益未到账」。
    【假设】续费/升档为**覆盖式**发放（次数按档位额度重置，不累加；valid_to 从本次
    paid_at 起算），文档未定义叠加规则。
    """
    conf = PLAN_TIERS[tier]
    benefit = (
        await session.execute(
            select(UserBenefit).where(UserBenefit.user_id == user_id).with_for_update()
        )
    ).scalar_one_or_none()
    if benefit is None:
        benefit = UserBenefit(user_id=user_id)
        session.add(benefit)
        await session.flush()
    benefit.tier = tier
    benefit.ai_times_left = int(conf["ai_times"])
    benefit.coach_times_left = int(conf["coach_times"])
    valid_days = conf["valid_days"]
    benefit.valid_to = paid_at + timedelta(days=int(valid_days)) if valid_days else None
    return benefit


# ---------------------------------------------------------------------------
# 下单 / 支付 / 回调 / 列表
# ---------------------------------------------------------------------------


async def create_order(session: AsyncSession, user_id: int, tier: int) -> PlanOrder:
    """创建会员订阅订单：金额服务端按 tier 重算，15 分钟未支付过期。

    幂等：同一身份 + 同一 `Idempotency-Key` 在 `IDEMPOTENCY_TTL_SECONDS`（默认 300s）内
    重放由 `core/idempotency.py` 中间件拦在路由之前 → HTTP 409 + 4002；业务层不另造一套。
    """
    conf = PLAN_TIERS.get(tier)
    if conf is None:  # 兜底：pydantic 已限 1..3，防常量表缺项
        raise AppException(ErrorCode.VALIDATION_ERROR, "不支持的会员档位")
    order = PlanOrder(
        user_id=user_id,
        tier=tier,
        pay_amount=round(float(conf["price"]), 2),
        status=ORDER_STATUS_PENDING,
        order_no=_new_order_no(),
        expire_at=_now() + timedelta(minutes=ORDER_EXPIRE_MINUTES),
    )
    session.add(order)
    await session.commit()
    await session.refresh(order)
    return order


async def _mark_paid(session: AsyncSession, order: PlanOrder) -> None:
    """支付成功推进（mock pay 与 notify 收敛到同一实现）：1→2 + paid_at + 发放权益。"""
    order.status = ORDER_STATUS_PAID
    order.paid_at = _now()
    await _grant_benefit(session, order.user_id, order.tier, order.paid_at)


async def pay_order(
    session: AsyncSession, user_id: int, order_id: int, settings: Settings | None = None
) -> tuple[PlanOrder, dict[str, Any]]:
    """会员订单支付：校验归属 → 超时置取消并 5003 → mock 直接推进 / 否则微信预下单。"""
    order = (
        await session.execute(
            select(PlanOrder).where(PlanOrder.id == order_id, PlanOrder.user_id == user_id)
        )
    ).scalar_one_or_none()
    if order is None:  # 不存在/非本人统一 3001（行级隔离约定）
        raise AppException(ErrorCode.NOT_FOUND, "订单不存在")
    if order.status == ORDER_STATUS_PAID:  # 幂等：已支付重复支付返回当前状态
        return order, {}
    if order.status == ORDER_STATUS_CANCELED:
        raise AppException(ErrorCode.ORDER_TIMEOUT)
    if order.expire_at is not None and order.expire_at < _now():
        order.status = ORDER_STATUS_CANCELED
        await session.commit()
        raise AppException(ErrorCode.ORDER_TIMEOUT)

    s = settings or get_settings()
    if s.PAY_MOCK_MODE:  # 沙箱：直接推进支付成功（契约：pay_params 为空对象）
        await _mark_paid(session, order)
        await session.commit()
        return order, {}
    prep = await wechat_pay.prepare_payment(order, s)
    return order, prep.pay_params


async def handle_notify(session: AsyncSession, payload) -> dict[str, str]:
    """支付回调（无认证）：验签 → 幂等 → 防篡改 → 1→2 + 发放权益。

    - 验签失败 / 金额与订单应付不符 → 2001（契约 422）；
    - 订单不存在 → 3001；已取消 → 5003；超时未付 → 置取消 + 5003；
    - **业务幂等**：同一 order_no 重复回调应答 ok（微信协议要求，否则会持续重发）；
      「同 Idempotency-Key 重放 → 409 + 4002」由 `core/idempotency.py` 中间件负责。
    """
    order_no = payload.order_no
    try:
        amount = float(payload.amount)
    except (TypeError, ValueError) as exc:
        raise AppException(ErrorCode.VALIDATION_ERROR, "回调金额非法") from exc
    if not secrets.compare_digest(notify_sign(order_no, amount), payload.sign):
        raise AppException(ErrorCode.VALIDATION_ERROR, "回调验签失败")

    order = (
        await session.execute(
            select(PlanOrder).where(PlanOrder.order_no == order_no).with_for_update()
        )
    ).scalar_one_or_none()
    if order is None:
        raise AppException(ErrorCode.NOT_FOUND, "订单不存在")
    if order.status == ORDER_STATUS_PAID:  # 幂等：重复回调应答 ok
        return {"result": "ok"}
    if order.status == ORDER_STATUS_CANCELED:
        raise AppException(ErrorCode.ORDER_TIMEOUT, "订单已取消")
    if order.expire_at is not None and order.expire_at < _now():
        order.status = ORDER_STATUS_CANCELED
        await session.commit()
        raise AppException(ErrorCode.ORDER_TIMEOUT)
    if abs(amount - float(order.pay_amount)) > _AMOUNT_EPS:  # 防篡改
        raise AppException(ErrorCode.VALIDATION_ERROR, "回调金额与订单应付金额不符")

    await _mark_paid(session, order)
    await session.commit()
    return {"result": "ok"}


async def list_orders(
    session: AsyncSession, user_id: int, status: int | None, page: int, page_size: int
) -> tuple[list[PlanOrder], int]:
    """我的会员订阅订单（created_at DESC）。"""
    conds = [PlanOrder.user_id == user_id]
    if status is not None:
        conds.append(PlanOrder.status == status)
    total = int(
        (
            await session.execute(
                select(func.count()).select_from(PlanOrder).where(*conds)
            )
        ).scalar_one()
    )
    rows = (
        (
            await session.execute(
                select(PlanOrder)
                .where(*conds)
                .order_by(PlanOrder.created_at.desc(), PlanOrder.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return list(rows), total
