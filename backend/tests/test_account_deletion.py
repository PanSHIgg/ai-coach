"""G7 账号注销（`DELETE /api/account`）级联清除测试。

覆盖：单事务级联清除「有 ON DELETE CASCADE」与「无 CASCADE（需显式删）」两类关联表、
最终删除 user 行、返回契约 envelope、未登录 401、重复注销（token 指向已删用户）401。

为何单开文件：契约删除端点 `DELETE /api/account` 的级联清除为本轮 G7 新增行为，
现有 test_* 无账号注销用例，无可合并之处。
"""

from datetime import date

from sqlalchemy import func, select

from app.models import (
    AiDialog,
    BodyProfile,
    CouponPool,
    DailyCheckin,
    Food,
    MealRecord,
    Merchant,
    MerchantAccount,
    MerchantSku,
    Order,
    RedeemLog,
    TrackEvent,
    User,
    UserBenefit,
    UserPoints,
    UserTask,
    WeightRecord,
)


async def _count(db_session, model, user_id: int) -> int:
    return int(
        await db_session.scalar(
            select(func.count()).select_from(model).where(model.user_id == user_id)
        )
        or 0
    )


async def _seed_related(db_session, user_id: int) -> None:
    """造覆盖两类外键行为的关联数据：CASCADE（body/meal/…）+ 无 CASCADE（user_benefit/
    ai_dialog/order/track_event）。user_benefit 已由 authed 预置。

    其中「用户自建食物（owner_user_id）被 meal_record.food_id 引用」是真实正常流程：
    该父子边无 CASCADE，注销时须先删 meal_record 再删 food（否则外键违约）——即
    「按表名字母序删除会先删 food」的回归场景，由本用例一并覆盖（无需单列较弱用例）。
    """
    food = Food(name="清蒸鱼", calories_100g=120.0, status=1)
    custom_food = Food(name="自制止饿餐", calories_100g=88.0, status=1, owner_user_id=user_id)
    db_session.add_all([food, custom_food])
    await db_session.flush()
    db_session.add_all(
        [
            BodyProfile(
                user_id=user_id,
                gender=1,
                height_cm=175,
                age=30,
                current_weight=70.0,
                target_type=1,
                activity_level=2,
                goal_pace=1,
            ),
            MealRecord(
                user_id=user_id,
                record_date=date.today(),
                meal_type=2,
                food_id=food.id,
                food_name_snapshot="清蒸鱼",
                amount_g=150,
                calories=180.0,
                source=1,
            ),
            # 引用用户自建食物的饮食记录（food.owner_user_id → user，无 CASCADE）
            MealRecord(
                user_id=user_id,
                record_date=date.today(),
                meal_type=4,
                food_id=custom_food.id,
                food_name_snapshot="自制止饿餐",
                amount_g=200,
                calories=176.0,
                source=1,
            ),
            WeightRecord(user_id=user_id, weight=70.0, record_at=date.today()),
            UserPoints(user_id=user_id, balance=10, total_earned=10),
            DailyCheckin(user_id=user_id, checkin_date=date.today(), points=5),
            UserTask(user_id=user_id, task_code="daily_checkin", status=0),
            AiDialog(user_id=user_id, role="user", content="饿了能吃什么"),
            Order(
                order_no=f"TEST-DEL-{user_id}",
                user_id=user_id,
                total_amount=10.0,
                discount_amount=0.0,
                pay_amount=10.0,
                status=1,
            ),
            # 无外键但含 user_id 的埋点事件（track_event.user_id 无 FK）
            TrackEvent(event="scan_in", user_id=user_id, platform=1),
        ]
    )
    await db_session.commit()


async def test_delete_account_cascades_and_removes_user(db_client, db_session, authed):
    """DELETE /api/account：CASCADE 与无 CASCADE 关联行全清、自定义食物清除、user 行删除。"""
    user_id = authed["user_id"]
    await _seed_related(db_session, user_id)

    resp = await db_client.delete("/api/account", headers=authed["headers"])
    body = resp.json()
    assert (resp.status_code, body["code"]) == (200, 0)
    assert body["data"] == {"deleted": True}

    # 两类关联表该用户行数均为 0（user_benefit/ai_dialog/order 无 CASCADE；track_event 无 FK）
    for model in (
        BodyProfile,
        MealRecord,
        WeightRecord,
        UserPoints,
        DailyCheckin,
        UserTask,
        AiDialog,
        Order,
        UserBenefit,
        TrackEvent,
    ):
        assert await _count(db_session, model, user_id) == 0, model.__name__
    # 用户自定义食物（owner_user_id）
    assert (
        await db_session.scalar(
            select(func.count()).select_from(Food).where(Food.owner_user_id == user_id)
        )
        == 0
    )
    # 最终 user 行删除
    assert await db_session.scalar(select(User).where(User.id == user_id)) is None


async def test_delete_account_twice_second_returns_401(db_client, db_session, authed):
    """已注销用户的 token（user 行不存在）再次调用 → 401/1001（契约幂等口径）。"""
    first = await db_client.delete("/api/account", headers=authed["headers"])
    assert (first.status_code, first.json()["code"]) == (200, 0)

    second = await db_client.delete("/api/account", headers=authed["headers"])
    assert second.status_code == 401
    assert second.json()["code"] == 1001


async def test_delete_account_requires_auth_1001(db_client):
    """未登录调用 → 401/1001。"""
    resp = await db_client.delete("/api/account")
    assert resp.status_code == 401
    assert resp.json()["code"] == 1001


async def test_delete_account_merchant_owner_with_downstream_tables(db_client, db_session, authed):
    """商家所有者注销：merchant 被 coupon_pool/merchant_sku/merchant_account/order/redeem_log
    等「无 user_id 列」的下游表引用（FK 无 CASCADE）。

    修复前删除集合只含「FK→user ∪ 含 user_id 列」的表，这些下游表不在集合内，
    删 merchant 时先被其子表挡住 → FK 违约 → 接口 500。修复后应 200 且全部清除。
    """
    user_id = authed["user_id"]
    merchant = Merchant(name="轻食小馆", category="轻食", owner_user_id=user_id)
    db_session.add(merchant)
    await db_session.flush()
    db_session.add_all(
        [
            CouponPool(name="开业券", type=1, scope=1, merchant_id=merchant.id),
            MerchantSku(merchant_id=merchant.id, price=19.9),
            MerchantAccount(
                merchant_id=merchant.id, username=f"shop-{user_id}", password_hash="x"
            ),
        ]
    )
    order = Order(
        order_no=f"TEST-MER-{user_id}",
        user_id=user_id,
        merchant_id=merchant.id,
        total_amount=19.9,
        discount_amount=0.0,
        pay_amount=19.9,
        status=2,
    )
    db_session.add(order)
    await db_session.flush()
    db_session.add(RedeemLog(order_id=order.id, merchant_id=merchant.id, result=1))
    await db_session.commit()

    resp = await db_client.delete("/api/account", headers=authed["headers"])
    assert (resp.status_code, resp.json()["code"]) == (200, 0)
    assert resp.json()["data"] == {"deleted": True}

    async def _count_where(model, **filters) -> int:
        stmt = select(func.count()).select_from(model)
        for col, val in filters.items():
            stmt = stmt.where(getattr(model, col) == val)
        return int(await db_session.scalar(stmt) or 0)

    assert await _count_where(Merchant, owner_user_id=user_id) == 0
    assert await _count_where(MerchantSku, merchant_id=merchant.id) == 0
    assert await _count_where(CouponPool, merchant_id=merchant.id) == 0
    assert await _count_where(MerchantAccount, merchant_id=merchant.id) == 0
    assert await _count_where(Order, merchant_id=merchant.id) == 0
    assert await _count_where(RedeemLog, merchant_id=merchant.id) == 0
    assert await db_session.scalar(select(User).where(User.id == user_id)) is None


async def test_delete_account_redeemed_order_clears_redeem_log(db_client, db_session, authed):
    """已核销订单注销：order 被 redeem_log 引用（FK 无 CASCADE）。

    修复前 redeem_log 无 user_id 列、不在删除集合内，删 order 时被 redeem_log 挡住
    → FK 违约 → 500。修复后应 200 且 order/redeem_log 均清除。
    """
    user_id = authed["user_id"]
    order = Order(
        order_no=f"TEST-RDM-{user_id}",
        user_id=user_id,
        total_amount=10.0,
        discount_amount=0.0,
        pay_amount=10.0,
        status=3,
    )
    db_session.add(order)
    await db_session.flush()
    db_session.add(RedeemLog(order_id=order.id, result=1))
    await db_session.commit()

    resp = await db_client.delete("/api/account", headers=authed["headers"])
    assert (resp.status_code, resp.json()["code"]) == (200, 0)
    assert resp.json()["data"] == {"deleted": True}

    assert await _count(db_session, Order, user_id) == 0
    assert await db_session.scalar(
        select(func.count()).select_from(RedeemLog).where(RedeemLog.order_id == order.id)
    ) == 0