"""邀请裂变流程测试（CD-01/02/03/04/06）。

真源：01 §2.3.3（拍照 1 次算有效、同设备 1 次、2/5/10 三档）、10 §13.3（判定与次日批量发放）。
一个行为一个测试，三档用 parametrize 合并；库存/核销错误码见 test_orders.py。
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.security import create_access_token
from app.models import BodyProfile, Coupon, CouponPool, Food, Invite, User, UserBenefit
from app.services import invite_service as isvc

# ---------------------------------------------------------------------------
# 造数助手
# ---------------------------------------------------------------------------


async def _actor(db_session, openid: str, unionid: str | None = None) -> dict:
    user = User(openid=openid, unionid=unionid, nickname=openid, gender=1)
    db_session.add(user)
    await db_session.flush()
    db_session.add(UserBenefit(user_id=user.id, tier=0, ai_times_left=10))
    await db_session.commit()
    token = create_access_token(str(user.id), openid=user.openid)
    return {"user_id": user.id, "headers": {"Authorization": f"Bearer {token}"}}


async def _invite_pool(db_session) -> CouponPool:
    """平台通用券池（merchant_id IS NULL，不限量，长期有效）。"""
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
        valid_from=datetime.now(UTC) - timedelta(days=1),
        valid_to=datetime.now(UTC) + timedelta(days=365),
    )
    db_session.add(pool)
    await db_session.commit()
    return pool


async def _photo_once(db_client, db_session, authed: dict) -> None:
    """被邀请人完成第 1 次拍照记录（走 /api/meal 创建饮食记录）。"""
    food = Food(
        name=f"鸡胸肉-{authed['user_id']}",
        calories_100g=133.0,
        protein_100g=24.0,
        fat_100g=3.0,
        carb_100g=1.0,
        status=1,
    )
    db_session.add(food)
    db_session.add(
        BodyProfile(
            user_id=authed["user_id"],
            gender=1,
            height_cm=175,
            age=30,
            current_weight=70.0,
            target_type=1,
            activity_level=2,
            goal_pace=1,
        )
    )
    await db_session.commit()
    resp = await db_client.post(
        "/api/meal",
        headers=authed["headers"],
        json={"meal_type": 2, "food_id": food.id, "amount_g": 100, "source": 1},
    )
    assert resp.json()["code"] == 0, resp.text


async def _invite_status(db_session, invitee_id: int) -> int:
    return (
        await db_session.execute(select(Invite.status).where(Invite.invitee_id == invitee_id))
    ).scalar_one()


# ---------------------------------------------------------------------------
# CD-02：拍照前无效 / 拍照后转有效；同设备置无效
# ---------------------------------------------------------------------------


async def test_invite_invalid_until_first_photo(db_client, db_session):
    """绑定成功仅注册态（status=0，进度不计数）；完成第 1 次拍照记录后转有效。"""
    inviter = await _actor(db_session, "inv-a")
    invitee = await _actor(db_session, "inv-b")
    code = (
        await db_client.post("/api/invite", headers=inviter["headers"], json={})
    ).json()["data"]["invite_code"]

    bound = await db_client.post(
        "/api/invite", headers=invitee["headers"], json={"invite_code": code}
    )
    assert bound.json()["data"]["bound"] is True
    assert await _invite_status(db_session, invitee["user_id"]) == 0
    progress = (
        await db_client.get("/api/invite/progress", headers=inviter["headers"])
    ).json()["data"]
    assert progress["invitee_count"] == 0  # 拍照前无效

    await _photo_once(db_client, db_session, invitee)
    assert await _invite_status(db_session, invitee["user_id"]) == 1
    progress = (
        await db_client.get("/api/invite/progress", headers=inviter["headers"])
    ).json()["data"]
    assert progress["invitee_count"] == 1
    assert progress["next_tier"] == {"need": 1, "reward": "进阶版90天"}  # CD-04 档位文案


async def test_same_device_second_bind_marked_invalid(db_client, db_session):
    """同设备（同 unionid）第二次绑定 → status=2 无效，不计数。"""
    inviter1 = await _actor(db_session, "inv-dev-1")
    inviter2 = await _actor(db_session, "inv-dev-2")
    b1 = await _actor(db_session, "inv-dev-b1", unionid="same-device")
    b2 = await _actor(db_session, "inv-dev-b2", unionid="same-device")

    code1 = (
        await db_client.post("/api/invite", headers=inviter1["headers"], json={})
    ).json()["data"]["invite_code"]
    code2 = (
        await db_client.post("/api/invite", headers=inviter2["headers"], json={})
    ).json()["data"]["invite_code"]

    r1 = await db_client.post(
        "/api/invite", headers=b1["headers"], json={"invite_code": code1}
    )
    assert r1.json()["data"]["bound"] is True
    r2 = await db_client.post(
        "/api/invite", headers=b2["headers"], json={"invite_code": code2}
    )
    assert r2.json()["data"]["bound"] is True  # 关系落库但标记无效
    assert await _invite_status(db_session, b2["user_id"]) == 2

    # 拍照不改变无效判定（status=0 的激活只对注册态生效）
    await _photo_once(db_client, db_session, b2)
    assert await _invite_status(db_session, b2["user_id"]) == 2
    progress = (
        await db_client.get("/api/invite/progress", headers=inviter2["headers"])
    ).json()["data"]
    assert progress["invitee_count"] == 0


# ---------------------------------------------------------------------------
# CD-06：生效时刻双方各得 1 张券；券池无券静默跳过
# ---------------------------------------------------------------------------


async def test_invite_grants_coupon_to_both_sides(db_client, db_session):
    """status 0→1 生效时刻：邀请人与被邀请人各得 1 张平台通用券，granted_count+2。"""
    pool = await _invite_pool(db_session)
    inviter = await _actor(db_session, "inv-cpn-a")
    invitee = await _actor(db_session, "inv-cpn-b")
    code = (
        await db_client.post("/api/invite", headers=inviter["headers"], json={})
    ).json()["data"]["invite_code"]
    await db_client.post("/api/invite", headers=invitee["headers"], json={"invite_code": code})

    await _photo_once(db_client, db_session, invitee)

    for uid in (inviter["user_id"], invitee["user_id"]):
        coupons = (
            (
                await db_session.execute(
                    select(Coupon).where(
                        Coupon.obtain_user_id == uid, Coupon.obtain_way == 1
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(coupons) == 1
        assert coupons[0].pool_id == pool.id and coupons[0].status == 1
        assert coupons[0].merchant_id is None  # 平台通用券
    refreshed = (
        await db_session.execute(
            select(CouponPool)
            .where(CouponPool.id == pool.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert refreshed.granted_count == 2


async def test_invite_without_available_pool_still_activates(db_client, db_session):
    """券池无可发券：静默跳过，绑定生效不受阻断。"""
    inviter = await _actor(db_session, "inv-nopool-a")
    invitee = await _actor(db_session, "inv-nopool-b")
    code = (
        await db_client.post("/api/invite", headers=inviter["headers"], json={})
    ).json()["data"]["invite_code"]
    await db_client.post("/api/invite", headers=invitee["headers"], json={"invite_code": code})

    await _photo_once(db_client, db_session, invitee)  # 无任何券池行

    assert await _invite_status(db_session, invitee["user_id"]) == 1
    coupons = (await db_session.execute(select(Coupon))).scalars().all()
    assert coupons == []


# ---------------------------------------------------------------------------
# CD-03：2/5/10 三档发放（直调 service，等价次日批量任务）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("count", "tier", "days"),
    [(2, 1, 90), (5, 2, 180), (10, 3, None)],
)
async def test_tier_grant_by_threshold(db_session, count, tier, days):
    """有效邀请数达 2/5/10 → tier1/2/3；valid_to=now+90/180d，tier3 永久 NULL。"""
    inviter = User(openid=f"tier-inv-{count}", gender=1)
    db_session.add(inviter)
    await db_session.flush()
    db_session.add(UserBenefit(user_id=inviter.id, tier=0, ai_times_left=10))
    for i in range(count):
        invitee = User(openid=f"tier-inv-{count}-b{i}", gender=1)
        db_session.add(invitee)
        await db_session.flush()
        db_session.add(Invite(inviter_id=inviter.id, invitee_id=invitee.id, status=1))
    await db_session.commit()

    upgraded = await isvc.grant_pending_invite_rewards(db_session)
    assert upgraded == 1
    benefit = (
        await db_session.execute(
            select(UserBenefit).where(UserBenefit.user_id == inviter.id)
        )
    ).scalar_one()
    assert benefit.tier == tier
    if days is None:
        assert benefit.valid_to is None  # 永久·终身教练
    else:
        delta = (benefit.valid_to - benefit.valid_from).total_seconds()
        assert delta == pytest.approx(days * 86400)


async def test_reward_grant_idempotent_no_stack(db_session):
    """重复发放不叠加：tier 已达标不重写时间，第二轮 upgraded=0。"""
    inviter = User(openid="tier-idem", gender=1)
    db_session.add(inviter)
    await db_session.flush()
    db_session.add(UserBenefit(user_id=inviter.id, tier=0, ai_times_left=10))
    for i in range(2):
        invitee = User(openid=f"tier-idem-b{i}", gender=1)
        db_session.add(invitee)
        await db_session.flush()
        db_session.add(Invite(inviter_id=inviter.id, invitee_id=invitee.id, status=1))
    await db_session.commit()

    assert await isvc.grant_pending_invite_rewards(db_session) == 1
    first = (
        await db_session.execute(
            select(UserBenefit).where(UserBenefit.user_id == inviter.id)
        )
    ).scalar_one()
    before = (first.tier, first.valid_from, first.valid_to)

    assert await isvc.grant_pending_invite_rewards(db_session) == 0  # 不降级、不叠加
    again = (
        await db_session.execute(
            select(UserBenefit).where(UserBenefit.user_id == inviter.id)
        )
    ).scalar_one()
    assert (again.tier, again.valid_from, again.valid_to) == before


async def test_tier_upgrade_2_to_5_refreshes_validity(db_session):
    """有效邀请数 2→5 升档：tier1→tier2 单调升级，valid_from/valid_to 随档位刷新。"""
    inviter = User(openid="tier-up", gender=1)
    db_session.add(inviter)
    await db_session.flush()
    db_session.add(UserBenefit(user_id=inviter.id, tier=0, ai_times_left=10))
    for i in range(2):
        invitee = User(openid=f"tier-up-a{i}", gender=1)
        db_session.add(invitee)
        await db_session.flush()
        db_session.add(Invite(inviter_id=inviter.id, invitee_id=invitee.id, status=1))
    await db_session.commit()

    assert await isvc.grant_pending_invite_rewards(db_session) == 1
    benefit = (
        await db_session.execute(select(UserBenefit).where(UserBenefit.user_id == inviter.id))
    ).scalar_one()
    assert benefit.tier == 1
    first_from, first_to = benefit.valid_from, benefit.valid_to

    for i in range(3):  # 再邀 3 人 → 5 达 tier2
        invitee = User(openid=f"tier-up-b{i}", gender=1)
        db_session.add(invitee)
        await db_session.flush()
        db_session.add(Invite(inviter_id=inviter.id, invitee_id=invitee.id, status=1))
    await db_session.commit()

    assert await isvc.grant_pending_invite_rewards(db_session) == 1
    await db_session.refresh(benefit)  # 确认升级已落库
    assert benefit.tier == 2
    assert benefit.valid_from > first_from
    assert benefit.valid_to > first_to
    delta = (benefit.valid_to - benefit.valid_from).total_seconds()
    assert delta == pytest.approx(180 * 86400)
