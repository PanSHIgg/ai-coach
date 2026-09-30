"""邀请裂变服务（CD-03/CD-06）。

职责：
- **绑定生效**：被邀请人完成第 1 次拍照记录 → invite status 0→1（由
  `record_service.create_meal` 成功路径调用 `activate_invitee`）；
- **双方发券**：status 0→1 生效时刻，从 coupon_pool 取平台通用券
  （merchant_id IS NULL、在有效期、total_count=-1 或未发满）向邀请人与
  被邀请人各发 1 张；券池无可发券时静默跳过，不阻断【假设】；
- **档位权益**：按邀请人有效邀请数（status=1）达标发放 tier——
  2→tier1 进阶版 90 天 / 5→tier2 进阶版 180 天 / 10→tier3 永久·终身教练
  （valid_to=NULL）。tier 单调升级 + 不降级防重，单人时间型奖励上限 180 天、
  永久档为终身身份【假设】。按 10 文档 §13.3：定时批量、次日发放、失败重试 3 次
  （本服务为独立可直调函数；后台循环 `start_reward_scheduler` 每日一次 + 启动跑一次）。
"""

import asyncio
import secrets
import string
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import get_sessionmaker
from app.models import Coupon, CouponPool, Invite, UserBenefit
from app.services.ai_service import ai_quota_for_tier

logger = get_logger(__name__)

# (达标人数, tier, 时长天数 None=永久)
TIER_THRESHOLDS: tuple[tuple[int, int, int | None], ...] = ((2, 1, 90), (5, 2, 180), (10, 3, None))

REWARD_INTERVAL_SECONDS = 24 * 3600  # 次日批量：每日一轮
_REWARD_RETRY = 3  # 10 文档：失败重试 3 次
_ALNUM = string.ascii_uppercase + string.digits
_CODE_ATTEMPTS = 5


def _now() -> datetime:
    return datetime.now(UTC)


def next_tier_for(count: int) -> int:
    """按有效邀请数算应达档位（单调，0 基础）。"""
    target = 0
    for need, tier, _days in TIER_THRESHOLDS:
        if count >= need:
            target = tier
    return target


# ---------------------------------------------------------------------------
# 双方发券（CD-06）
# ---------------------------------------------------------------------------


async def _gen_coupon_codes(session: AsyncSession, count: int) -> list[str]:
    """生成 count 个不冲突券码：CP + 8 位大写字母数字（唯一约束兜底）。"""
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
        return []
    return list(codes)[:count]


async def grant_invite_coupons(session: AsyncSession, user_ids: list[int]) -> bool:
    """从券池取平台通用券向给定用户各发 1 张；无可发券返回 False。

    只写不提交，由调用方与激活同事务统一提交（激活+发券原子性）。
    """
    now = _now()
    pool = (
        await session.execute(
            select(CouponPool)
            .where(
                CouponPool.merchant_id.is_(None),  # 平台通用券
                CouponPool.status == 1,
                or_(CouponPool.valid_from.is_(None), CouponPool.valid_from <= now),
                or_(CouponPool.valid_to.is_(None), CouponPool.valid_to >= now),
                or_(
                    CouponPool.total_count == -1,
                    CouponPool.granted_count < CouponPool.total_count,
                ),
            )
            .order_by(CouponPool.id)
            .with_for_update()
            .limit(1)
        )
    ).scalar_one_or_none()
    if pool is None:  # 券池无可发券：静默跳过，不阻断绑定
        return False
    codes = await _gen_coupon_codes(session, len(user_ids))
    if len(codes) < len(user_ids):
        return False
    session.add_all(
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
            obtain_way=1,  # 1邀请（04 文档：1邀请 2任务 3平台补贴 4注册礼）
            obtain_user_id=user_id,
            status=1,
            valid_from=pool.valid_from,
            valid_to=pool.valid_to,
        )
        for user_id, code in zip(user_ids, codes, strict=True)
    )
    pool.granted_count += len(user_ids)
    return True


# ---------------------------------------------------------------------------
# 绑定生效（CD-02/CD-06 挂钩点）
# ---------------------------------------------------------------------------


async def activate_invitee(invitee_id: int) -> None:
    """被邀请人完成第 1 次拍照记录 → invite 0→1 + 双方各发 1 张券。

    激活+发券走**独立 session**（与拍照主事务解耦：本函数任何失败只记日志，
    绝不影响 create_meal 主流程）；激活用原子 UPDATE ... WHERE status=0 判
    rowcount —— 并发首拍仅一方置 1 成功并发券，另一方 rowcount=0 直接返回。
    """
    try:
        async with get_sessionmaker()() as isession:
            row = (
                await isession.execute(
                    update(Invite)
                    .where(Invite.invitee_id == invitee_id, Invite.status == 0)
                    .values(status=1)
                    .returning(Invite.inviter_id)
                )
            ).first()
            if row is None:  # 无注册态绑定 / 已被并发请求激活
                return
            user_ids = [uid for uid in (row.inviter_id, invitee_id) if uid is not None]
            await grant_invite_coupons(isession, user_ids)
            await isession.commit()  # 激活+发券同一事务原子提交
    except Exception as exc:  # noqa: BLE001 - 激活/发券失败只记日志，不影响拍照主流程
        logger.warning(
            "邀请生效/发券失败", extra={"invitee_id": invitee_id, "reason": str(exc)}
        )


# ---------------------------------------------------------------------------
# 档位权益批量发放（CD-03）
# ---------------------------------------------------------------------------


def _valid_to_for(tier: int, base: datetime) -> datetime | None:
    """档位对应有效期终点；tier3 永久 → NULL。"""
    days = next((d for _need, t, d in TIER_THRESHOLDS if t == tier), None)
    return None if days is None else base + timedelta(days=days)


async def grant_pending_invite_rewards(session: AsyncSession) -> int:
    """按有效邀请数（status=1）达档发放 tier，返回升级人数。

    - tier 单调升级 + 不降级防重：tier 已达标（>= 目标）不再写时间；
    - 升级时写 valid_from=now、valid_to=now+时长（tier3 永久 NULL），**同步把
      `ai_times_left` 提升到该档配额**（见 ai_service.TIER_AI_QUOTA【假设】），
      使「邀请 → AI 次数扩容」链路生效（主文档 §111/§133/§184）；
    - 重复发放不叠加（幂等）：仅在 tier 升档时改为更高配额，不回退、不重复加；
    - 单用户失败重试 3 次（10 文档 §13.3），重试仍失败跳过该用户。
    """
    rows = (
        await session.execute(
            select(Invite.inviter_id, func.count())
            .where(Invite.status == 1, Invite.inviter_id.is_not(None))
            .group_by(Invite.inviter_id)
        )
    ).all()
    now = _now()
    daily = get_settings().AI_DAILY_TIMES
    upgraded = 0
    for user_id, count in rows:
        target = next_tier_for(int(count))
        if target <= 0:
            continue
        quota = ai_quota_for_tier(target, daily)
        for attempt in range(_REWARD_RETRY):
            try:
                benefit = (
                    await session.execute(
                        select(UserBenefit).where(UserBenefit.user_id == int(user_id))
                    )
                ).scalar_one_or_none()
                if benefit is None:
                    session.add(
                        UserBenefit(
                            user_id=int(user_id),
                            tier=target,
                            ai_times_left=quota,
                            valid_from=now,
                            valid_to=_valid_to_for(target, now),
                        )
                    )
                    upgraded += 1
                elif benefit.tier < target:  # 单调升级，不降级、不重复发放
                    benefit.tier = target
                    benefit.valid_from = now
                    benefit.valid_to = _valid_to_for(target, now)
                    # 提升到该档配额（保留更高的既有余额，不降额）
                    benefit.ai_times_left = max(int(benefit.ai_times_left or 0), quota)
                    upgraded += 1
                await session.commit()
                break
            except Exception as exc:  # noqa: BLE001 - 单用户失败重试，不影响其余
                await session.rollback()
                if attempt == _REWARD_RETRY - 1:
                    logger.warning(
                        "邀请权益发放失败（已重试 3 次）",
                        extra={"user_id": user_id, "reason": str(exc)},
                    )
    if upgraded:
        logger.info("邀请权益发放完成", extra={"upgraded": upgraded})
    return upgraded


# ---------------------------------------------------------------------------
# 后台循环（定时批量；项目无 Celery/APScheduler 基建，用最简 asyncio 实现【假设】）
# ---------------------------------------------------------------------------


async def run_reward_once() -> int:
    """自建会话跑一轮发放（启动时 / 每日各一次）。"""
    async with get_sessionmaker()() as session:
        return await grant_pending_invite_rewards(session)


async def _reward_loop() -> None:
    """启动时先跑一次，此后每日一次；异常消化，永不退出。"""
    while True:
        try:
            await run_reward_once()
        except Exception as exc:  # noqa: BLE001 - 调度循环永不因异常退出
            logger.warning("邀请权益定时任务失败", extra={"reason": str(exc)})
        await asyncio.sleep(REWARD_INTERVAL_SECONDS)


def start_reward_scheduler() -> asyncio.Task | None:
    """启动后台发放循环；无运行中事件循环时返回 None（如同步导入场景）。"""
    try:
        return asyncio.get_running_loop().create_task(_reward_loop())
    except RuntimeError:
        return None
