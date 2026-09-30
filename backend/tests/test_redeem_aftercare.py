"""核销后三件套测试（01 文档 §2.3.2）：摄入自动写入 / 商家贡献分 / 社区经验卡。

一个行为一个测试 + 1 条事务回滚用例（经验卡生成失败 → 核销整体回滚）；
数据直接落 ORM（沿用 test_orders.py 造数思路）。sku_catalog 为库内种子目录，
conftest 不清空。
"""

from sqlalchemy import func, select

from app.core.errors import AppException
from app.models import (
    CommunityPost,
    MealRecord,
    Merchant,
    MerchantSku,
    Order,
    RedeemLog,
    SkuCatalog,
)
from app.services import redeem_aftercare
from app.services.order_service import notify_sign

# ---------------------------------------------------------------------------
# 造数助手（同 test_orders.py 口径）
# ---------------------------------------------------------------------------


async def _seed_merchant(db_session, name="轻食一号店", category="轻食"):
    m = Merchant(name=name, category=category, status=1, audit_status=1)
    db_session.add(m)
    await db_session.commit()
    return m


async def _seed_sku(db_session, merchant_id, code="FD-001", price=25.0):
    catalog_id = (
        await db_session.execute(select(SkuCatalog.id).where(SkuCatalog.code == code))
    ).scalar_one()
    sku = MerchantSku(
        merchant_id=merchant_id, catalog_id=catalog_id, price=price, stock=-1, status=1
    )
    db_session.add(sku)
    await db_session.commit()
    return sku


async def _paid_order(db_client, db_session, authed, merchant, qty=1) -> Order:
    sku = await _seed_sku(db_session, merchant.id)
    resp = await db_client.post(
        "/api/order",
        headers=authed["headers"],
        json={"merchant_id": merchant.id, "items": [{"sku_id": sku.id, "qty": qty}]},
    )
    assert resp.status_code == 200, resp.text
    d = resp.json()["data"]
    notify = await db_client.post(
        "/api/order/notify", json=_notify(d["order_no"], d["pay_amount"])
    )
    assert notify.status_code == 200, notify.text
    return (
        await db_session.execute(
            select(Order).where(Order.id == d["order_id"]).execution_options(populate_existing=True)
        )
    ).scalar_one()


def _notify(order_no: str, amount: float) -> dict:
    return {"order_no": order_no, "amount": amount, "sign": notify_sign(order_no, amount)}


async def _redeem(db_client, authed, order: Order, merchant_id: int):
    return await db_client.post(
        f"/api/order/{order.id}/redeem",
        headers=authed["headers"],
        json={"redeem_code": order.redeem_code, "merchant_id": merchant_id},
    )


async def _get_order(db_session, order_id) -> Order:
    return (
        await db_session.execute(
            select(Order).where(Order.id == order_id).execution_options(populate_existing=True)
        )
    ).scalar_one()


async def _get_merchant(db_session, merchant_id) -> Merchant:
    return (
        await db_session.execute(
            select(Merchant)
            .where(Merchant.id == merchant_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


# ---------------------------------------------------------------------------
# 三件套：一个行为一个测试
# ---------------------------------------------------------------------------


async def test_redeem_writes_meal_records_from_order_sku(db_client, db_session, authed):
    """① 摄入自动写入：核销成功后按订单项写 meal_record（source=5，卡路里=目录区间中位）。"""
    m = await _seed_merchant(db_session)
    order = await _paid_order(db_client, db_session, authed, m)  # FD-001 300-450 kcal × 1

    resp = await _redeem(db_client, authed, order, m.id)
    assert resp.status_code == 200, resp.text

    records = (
        (await db_session.execute(select(MealRecord).where(MealRecord.user_id == authed["user_id"])))
        .scalars()
        .all()
    )
    assert len(records) == 1
    r = records[0]
    assert r.food_name_snapshot == "经典鸡胸减脂餐"  # 订单项 SKU 快照
    assert r.calories == 375.0  # (300+450)/2 × 1
    assert int(r.source) == 5  # 【假设】订单核销来源
    assert r.record_date is not None and int(r.meal_type) in (1, 2, 3, 4)


async def test_redeem_adds_merchant_contribution_points(db_client, db_session, authed):
    """② 商家贡献分：核销成功后 merchant.contribution_points 累加 +1。"""
    m = await _seed_merchant(db_session)
    order = await _paid_order(db_client, db_session, authed, m)
    assert (await _get_merchant(db_session, m.id)).contribution_points == 0

    resp = await _redeem(db_client, authed, order, m.id)
    assert resp.status_code == 200, resp.text
    assert (await _get_merchant(db_session, m.id)).contribution_points == 1


async def test_redeem_creates_experience_post(db_client, db_session, authed):
    """③ 社区经验卡：核销成功后生成 post_type=2 动态，内容含商家名与订单号。"""
    m = await _seed_merchant(db_session)
    order = await _paid_order(db_client, db_session, authed, m)

    resp = await _redeem(db_client, authed, order, m.id)
    assert resp.status_code == 200, resp.text

    posts = (
        (
            await db_session.execute(
                select(CommunityPost).where(
                    CommunityPost.user_id == authed["user_id"],
                    CommunityPost.post_type == 2,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(posts) == 1
    post = posts[0]
    assert post.audit_status == 1  # 读取侧 list_experience 仅展示 audit_status=1
    assert "轻食一号店" in post.title
    assert order.order_no in post.content and "轻食一号店" in post.content


async def test_redeem_rolls_back_all_when_experience_card_fails(db_client, db_session, authed, monkeypatch):
    """事务回滚：经验卡生成失败 → 核销整体回滚（状态/留痕/摄入/贡献分/经验卡零残留）。"""

    def _boom(session, order, merchant, items):
        raise AppException(500, "经验卡生成失败")

    m = await _seed_merchant(db_session)
    order = await _paid_order(db_client, db_session, authed, m)
    monkeypatch.setattr(redeem_aftercare, "create_experience_card", _boom)

    resp = await _redeem(db_client, authed, order, m.id)
    assert resp.status_code == 500

    assert (await _get_order(db_session, order.id)).status == 2  # 未完成流转
    assert (
        await db_session.scalar(select(func.count()).select_from(RedeemLog))
    ) == 0  # 成功留痕一并回滚
    assert (await db_session.scalar(select(func.count()).select_from(MealRecord))) == 0
    assert (await db_session.scalar(select(func.count()).select_from(CommunityPost))) == 0
    assert (await _get_merchant(db_session, m.id)).contribution_points == 0
