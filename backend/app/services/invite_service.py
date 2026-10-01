"""邀请裂变服务（新口径：docs/changes/2026-10-01-邀请规则变更记录.md）。

职责（绑定事务内原子完成，实时生效）：
- **注册即有效**：被邀请人注册绑定成功即插 status=1 的 invite 记录，不要求
  建档/拍照/后续活跃；status 保留恒为 1（扩展位）；
- **防刷**：同设备只计 1 次——绑定请求带可选 device_id，该设备已在 invite 表
  出现过（全局，不含当前这条）→ 抛 4102 INVITE_ABUSE；
- **档位权益**：按邀请人有效邀请数（status=1 count）达标升档——
  1→tier1（20 次/日）/ 3→tier2（40 次/日）/ 10→tier3（不限次·永久终身版）；
  升级时把 ai_times_left 提到新档配额（保留更高余额不降额）；
- **无期限**：权益不回收、无有效期（user_benefit 无 valid_from/valid_to）。
只算直接邀请，无多级裂变；无发券、无次日批量调度。
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppException
from app.core.logging import get_logger
from app.models import Invite, UserBenefit
from app.schemas.common import ErrorCode
from app.services.ai_service import ai_quota_for_tier

logger = get_logger(__name__)

# 档位阈值（docs/changes/2026-10-01-邀请规则变更记录.md §二）：累计有效邀请数达
# 1/3/10 人分别对应 tier1/2/3；0 人为 tier0 基础版。只算直接邀请，无期限。
INVITE_TIERS: tuple[int, ...] = (1, 3, 10)


def next_tier_for(count: int) -> int:
    """按有效邀请数算应达档位（单调，0 基础）。"""
    target = 0
    for tier, need in enumerate(INVITE_TIERS, start=1):
        if count >= need:
            target = tier
    return target


async def activate_and_grant(
    session: AsyncSession, *, inviter_id: int, invitee_id: int, device_id: str | None = None
) -> None:
    """绑定即生效：原子插 status=1 记录 + 防刷检查 + 邀请人实时升档。

    由 community.create_invite 在**绑定事务内**调用（只写不提交，与绑定同事务
    原子提交）：
    - 防刷（4102）：device_id 非空且已在 invite 表出现过（全局，不含当前这条，
      即排除被邀请人本人的既有行）→ 拦截，同设备只计 1 次；
    - 升档：统计 inviter 有效邀请数（status=1 count，先 flush 使本条计入），
      next_tier_for 达档则升 UserBenefit.tier 并把 ai_times_left 提到新档配额
      （保留更高余额不降额；tier3 不限次配额为 -1，不覆盖既有余额）。
    """
    if device_id:
        dup = await session.scalar(
            select(Invite.id).where(Invite.device_id == device_id, Invite.invitee_id != invitee_id)
        )
        if dup is not None:
            raise AppException(ErrorCode.INVITE_ABUSE)  # 防刷拦截：同设备只计 1 次
    session.add(Invite(inviter_id=inviter_id, invitee_id=invitee_id, status=1, device_id=device_id))
    await session.flush()  # 本条计入有效邀请统计（同事务可见）
    count = int(
        await session.scalar(
            select(func.count())
            .select_from(Invite)
            .where(Invite.inviter_id == inviter_id, Invite.status == 1)
        )
        or 0
    )
    target = next_tier_for(count)
    if target <= 0:
        return
    quota = ai_quota_for_tier(target, get_settings().AI_DAILY_TIMES)
    benefit = (
        await session.execute(select(UserBenefit).where(UserBenefit.user_id == inviter_id))
    ).scalar_one_or_none()
    if benefit is None:
        session.add(UserBenefit(user_id=inviter_id, tier=target, ai_times_left=max(quota, 0)))
    elif benefit.tier < target:  # 单调升级，不降级
        benefit.tier = target
        if quota > 0:  # tier3=-1 不限次：不覆盖余额（无期限、不回收）
            benefit.ai_times_left = max(int(benefit.ai_times_left or 0), quota)
    logger.info(
        "邀请绑定生效", extra={"inviter_id": inviter_id, "invitee_id": invitee_id, "tier": target}
    )
