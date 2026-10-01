"""邀请裂变流程测试（新口径：docs/changes/2026-10-01-邀请规则变更记录.md）。

口径：注册即有效（绑定即生效、实时升档）、只算直接邀请、档位 INVITE_TIERS=[1,3,10]
（1→tier1 20次/日、3→tier2 40次/日、10→tier3 不限次·终身）、无期限、同设备只计 1 次
（4102）、废除双方发券、删除次日批量调度。一个行为一个测试；库存/核销错误码见 test_orders.py。
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import create_access_token
from app.models import Coupon, CouponPool, Invite, User, UserBenefit
from app.schemas.common import ErrorCode
from app.services import invite_service as isvc

# ---------------------------------------------------------------------------
# 造数助手
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


async def _actor(db_session, openid: str) -> dict:
    user = User(openid=openid, nickname=openid, gender=1)
    db_session.add(user)
    await db_session.flush()
    db_session.add(UserBenefit(user_id=user.id, tier=0, ai_times_left=10))
    await db_session.commit()
    token = create_access_token(str(user.id), openid=user.openid)
    return {"user_id": user.id, "headers": {"Authorization": f"Bearer {token}"}}


async def _invite_status(db_session, invitee_id: int) -> int:
    return (
        await db_session.execute(select(Invite.status).where(Invite.invitee_id == invitee_id))
    ).scalar_one()


# ---------------------------------------------------------------------------
# 纯函数单元（不依赖 DB）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("count", "tier"),
    [(0, 0), (1, 1), (2, 1), (3, 2), (9, 2), (10, 3), (11, 3)],
)
def test_next_tier_for_mapping(count, tier):
    """INVITE_TIERS=[1,3,10]：0 人 tier0 基础，1/3/10 人达 tier1/2/3（单调）。"""
    assert isvc.INVITE_TIERS == (1, 3, 10)
    assert isvc.next_tier_for(count) == tier


@pytest.mark.parametrize(
    ("tier", "quota"),
    [(0, 10), (1, 20), (2, 40), (3, -1)],
)
def test_ai_quota_for_tier_mapping(tier, quota):
    """配额映射：tier0=10（AI_DAILY_TIMES 默认）、tier1=20、tier2=40、tier3=-1 不限次。"""
    daily = get_settings().AI_DAILY_TIMES
    assert isvc.ai_quota_for_tier(tier, daily) == quota


def test_no_batch_scheduler_and_coupon_chain():
    """实时生效：次日批量调度与发券链路已整体删除。"""
    for legacy in (
        "start_reward_scheduler",
        "_reward_loop",
        "run_reward_once",
        "REWARD_INTERVAL_SECONDS",
        "grant_invite_coupons",
        "_gen_coupon_codes",
        "grant_pending_invite_rewards",
        "activate_invitee",
    ):
        assert not hasattr(isvc, legacy), legacy


# ---------------------------------------------------------------------------
# 绑定即生效（注册即有效）
# ---------------------------------------------------------------------------


async def test_bind_effective_immediately(db_client, db_session):
    """注册即有效：绑定成功即 status=1 计数，无需建档/拍照；邀请人实时升 tier1。"""
    inviter = await _actor(db_session, "inv-a")
    invitee = await _actor(db_session, "inv-b")
    code = (await db_client.post("/api/invite", headers=inviter["headers"], json={})).json()[
        "data"
    ]["invite_code"]

    bound = await db_client.post(
        "/api/invite", headers=invitee["headers"], json={"invite_code": code}
    )
    assert bound.json()["data"]["bound"] is True
    assert await _invite_status(db_session, invitee["user_id"]) == 1  # 注册即有效

    progress = (await db_client.get("/api/invite/progress", headers=inviter["headers"])).json()[
        "data"
    ]
    assert progress["invitee_count"] == 1  # 绑定即计数
    assert progress["next_tier"] == {"need": 2, "reward": "高级版40次/日"}  # 下一档 3 人

    benefit = (
        await db_session.execute(
            select(UserBenefit).where(UserBenefit.user_id == inviter["user_id"])
        )
    ).scalar_one()
    assert benefit.tier == 1  # 绑定事务内实时升档
    assert benefit.ai_times_left == 20  # 提到 tier1 配额


async def test_bind_keeps_higher_balance(db_session):
    """升档不降额：既有余额高于新档配额时保留原余额。"""
    inviter = User(openid="inv-keep", gender=1)
    db_session.add(inviter)
    await db_session.flush()
    db_session.add(UserBenefit(user_id=inviter.id, tier=0, ai_times_left=25))
    invitee = User(openid="inv-keep-b", gender=1)
    db_session.add(invitee)
    await db_session.commit()

    await isvc.activate_and_grant(db_session, inviter_id=inviter.id, invitee_id=invitee.id)
    await db_session.commit()
    benefit = (
        await db_session.execute(select(UserBenefit).where(UserBenefit.user_id == inviter.id))
    ).scalar_one()
    assert benefit.tier == 1
    assert benefit.ai_times_left == 25  # 25 > 20，不降额


async def test_tier_progression_1_3_10(db_session):
    """档位推进：1 人 tier1（20）、3 人 tier2（40）、10 人 tier3 不限次（无期限）。"""
    inviter = User(openid="tier-prog", gender=1)
    db_session.add(inviter)
    await db_session.flush()
    db_session.add(UserBenefit(user_id=inviter.id, tier=0, ai_times_left=10))

    async def bind(i: int) -> None:
        invitee = User(openid=f"tier-prog-b{i}", gender=1)
        db_session.add(invitee)
        await db_session.flush()
        await isvc.activate_and_grant(db_session, inviter_id=inviter.id, invitee_id=invitee.id)
        await db_session.commit()

    for i in range(10):
        await bind(i)
        benefit = (
            await db_session.execute(select(UserBenefit).where(UserBenefit.user_id == inviter.id))
        ).scalar_one()
        if i == 0:
            assert (benefit.tier, benefit.ai_times_left) == (1, 20)
        elif i == 2:
            assert (benefit.tier, benefit.ai_times_left) == (2, 40)
        elif i == 9:
            assert benefit.tier == 3
            assert benefit.ai_times_left == 40  # tier3 不限次：不覆盖余额
    # 只算直接邀请：无多级裂变，被邀请人的邀请不计入邀请人
    count = len(
        (
            await db_session.execute(
                select(Invite.id).where(Invite.inviter_id == inviter.id, Invite.status == 1)
            )
        )
        .scalars()
        .all()
    )
    assert count == 10


async def test_progress_at_tier3(db_client, db_session):
    """已达 10 人：next_tier need=0、reward=终身版不限次。"""
    inviter = await _actor(db_session, "inv-full")
    for i in range(10):
        invitee = User(openid=f"inv-full-b{i}", gender=1)
        db_session.add(invitee)
        await db_session.flush()
        db_session.add(Invite(inviter_id=inviter["user_id"], invitee_id=invitee.id, status=1))
    await db_session.commit()
    progress = (await db_client.get("/api/invite/progress", headers=inviter["headers"])).json()[
        "data"
    ]
    assert progress["invitee_count"] == 10
    assert progress["next_tier"] == {"need": 0, "reward": "终身版不限次"}


# ---------------------------------------------------------------------------
# 防刷（4102）：同设备只计 1 次
# ---------------------------------------------------------------------------


async def test_same_device_second_bind_rejected_4102(db_client, db_session):
    """同 device_id 已在 invite 表出现过（全局）→ 再次绑定返回 4102，不落库。"""
    inviter1 = await _actor(db_session, "inv-dev-1")
    inviter2 = await _actor(db_session, "inv-dev-2")
    b1 = await _actor(db_session, "inv-dev-b1")
    b2 = await _actor(db_session, "inv-dev-b2")
    code1 = (await db_client.post("/api/invite", headers=inviter1["headers"], json={})).json()[
        "data"
    ]["invite_code"]
    code2 = (await db_client.post("/api/invite", headers=inviter2["headers"], json={})).json()[
        "data"
    ]["invite_code"]

    r1 = await db_client.post(
        "/api/invite", headers=b1["headers"], json={"invite_code": code1, "device_id": "dev-x"}
    )
    assert r1.json()["data"]["bound"] is True

    r2 = await db_client.post(
        "/api/invite", headers=b2["headers"], json={"invite_code": code2, "device_id": "dev-x"}
    )
    assert r2.json()["code"] == ErrorCode.INVITE_ABUSE == 4102  # 防刷拦截
    assert r2.status_code == 409
    assert (
        await db_session.scalar(select(Invite.id).where(Invite.invitee_id == b2["user_id"]))
    ) is None  # 未落库

    # 换设备可正常绑定（防刷只针对同设备）
    r3 = await db_client.post(
        "/api/invite", headers=b2["headers"], json={"invite_code": code2, "device_id": "dev-y"}
    )
    assert r3.json()["data"]["bound"] is True


# ---------------------------------------------------------------------------
# 绑定边界：自邀请 / 重复绑定
# ---------------------------------------------------------------------------


async def test_self_invite_rejected(db_client, authed):
    """绑定自己的邀请码 → 2001。"""
    code = (await db_client.post("/api/invite", headers=authed["headers"], json={})).json()["data"][
        "invite_code"
    ]
    r = await db_client.post("/api/invite", headers=authed["headers"], json={"invite_code": code})
    assert r.status_code == 422
    assert r.json()["code"] == ErrorCode.VALIDATION_ERROR


async def test_duplicate_bind_rejected(db_client, db_session):
    """一人只能被邀请一次（UNIQUE invitee_id）：重复绑定 → 2001。"""
    inviter1 = await _actor(db_session, "inv-dup-1")
    inviter2 = await _actor(db_session, "inv-dup-2")
    invitee = await _actor(db_session, "inv-dup-b")
    code1 = (await db_client.post("/api/invite", headers=inviter1["headers"], json={})).json()[
        "data"
    ]["invite_code"]
    code2 = (await db_client.post("/api/invite", headers=inviter2["headers"], json={})).json()[
        "data"
    ]["invite_code"]

    r1 = await db_client.post(
        "/api/invite", headers=invitee["headers"], json={"invite_code": code1}
    )
    assert r1.json()["data"]["bound"] is True
    r2 = await db_client.post(
        "/api/invite", headers=invitee["headers"], json={"invite_code": code2}
    )
    assert r2.status_code == 422
    assert r2.json()["code"] == ErrorCode.VALIDATION_ERROR


# ---------------------------------------------------------------------------
# 废除双方发券：绑定/升档全程无券
# ---------------------------------------------------------------------------


async def test_no_coupons_granted_on_bind(db_client, db_session):
    """新规则无发券：券池可发也不产生券，pool.granted_count 不变。"""
    pool = CouponPool(
        name="邀请通用券",
        type=1,
        scope=4,
        amount=5.0,
        min_spend=0,
        merchant_id=None,
        total_count=-1,
        granted_count=0,
        status=1,
    )
    db_session.add(pool)
    await db_session.commit()

    inviter = await _actor(db_session, "inv-nocpn-a")
    invitee = await _actor(db_session, "inv-nocpn-b")
    code = (await db_client.post("/api/invite", headers=inviter["headers"], json={})).json()[
        "data"
    ]["invite_code"]
    await db_client.post("/api/invite", headers=invitee["headers"], json={"invite_code": code})

    coupons = (await db_session.execute(select(Coupon))).scalars().all()
    assert coupons == []  # 无任何发券
    refreshed = (
        await db_session.execute(
            select(CouponPool)
            .where(CouponPool.id == pool.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert refreshed.granted_count == 0


# ---------------------------------------------------------------------------
# tier3 不限次：扣减链路遇 -1 不扣不拦
# ---------------------------------------------------------------------------


class _StubLLM:
    """直调 chat() 用的桩客户端：绕开真实 LLM。"""

    async def achat(self, messages: list[dict]) -> str:
        return "测试回复"


async def test_tier3_unlimited_chat_no_deduct(db_session):
    """tier3（-1）不限次：余额为 0 也不拦截、不扣减，times_left 响应 int 不变。"""
    user = User(openid="inv-tier3", gender=1)
    db_session.add(user)
    await db_session.flush()
    db_session.add(UserBenefit(user_id=user.id, tier=3, ai_times_left=0))
    await db_session.commit()

    from app.services import ai_service

    result = await ai_service.chat(
        db_session,
        user_id=user.id,
        session_id=None,
        message="今天吃什么",
        settings=get_settings(),
        llm_client=_StubLLM(),
    )
    assert result.times_left == 0  # 未扣减
    benefit = (
        await db_session.execute(select(UserBenefit).where(UserBenefit.user_id == user.id))
    ).scalar_one()
    assert int(benefit.ai_times_left) == 0  # 不限次不写余额


async def test_tier0_exhausted_still_blocked(db_session):
    """对照：tier0 余额用尽仍返 4001（-1 仅对 tier3 生效）。"""
    user = User(openid="inv-tier0", gender=1)
    db_session.add(user)
    await db_session.flush()
    # ai_times_reset_at=now：避开 ensure_benefit 的每日重置，验证余额 0 确实被拦
    db_session.add(UserBenefit(user_id=user.id, tier=0, ai_times_left=0, ai_times_reset_at=_now()))
    await db_session.commit()

    from app.core.errors import AppException
    from app.services import ai_service

    with pytest.raises(AppException) as exc_info:
        await ai_service.chat(
            db_session,
            user_id=user.id,
            session_id=None,
            message="今天吃什么",
            settings=get_settings(),
            llm_client=_StubLLM(),
        )
    assert exc_info.value.code == ErrorCode.QUOTA_EXCEEDED
