"""券域测试（BE6 Phase 3）：我的券分页 + scope/status 过滤 + 惰性过期展示。"""

import uuid
from datetime import UTC, datetime, timedelta

from app.models import Coupon, User

UTC = UTC


async def _seed_coupon(db_session, user_id, **kw) -> Coupon:
    now = datetime.now(UTC)
    fields = dict(
        code=f"CP-{uuid.uuid4().hex[:16]}",
        type=1,
        scope=1,
        amount=5.0,
        discount_rate=None,
        min_spend=0.0,
        merchant_id=None,
        status=1,
        valid_from=now - timedelta(days=1),
        valid_to=now + timedelta(days=30),
        obtain_user_id=user_id,
    )
    fields.update(kw)
    coupon = Coupon(**fields)
    db_session.add(coupon)
    await db_session.commit()
    return coupon


async def test_coupon_list_scope_status_and_lazy_expire(db_client, db_session, authed):
    """行级隔离；scope 过滤；未用但过有效期的券展示为 3（不改库）；status 过滤含惰性口径。"""
    uid = authed["user_id"]
    now = datetime.now(UTC)
    c1 = await _seed_coupon(db_session, uid, scope=1)  # 未用有效
    c2 = await _seed_coupon(db_session, uid, scope=2)  # 未用有效
    c3 = await _seed_coupon(
        db_session, uid, scope=1, valid_to=now - timedelta(days=1)  # 未用但已过期
    )
    c4 = await _seed_coupon(db_session, uid, scope=1, status=2)  # 已用
    other_user = User(openid="coupon-other", gender=1)
    db_session.add(other_user)
    await db_session.commit()
    await _seed_coupon(db_session, other_user.id, scope=1)  # 别人的券

    resp = await db_client.get("/api/coupon/list", headers=authed["headers"])
    body = resp.json()
    assert resp.status_code == 200 and body["code"] == 0
    data = body["data"]
    assert data["page"]["total"] == 4  # 不含他人券
    status_by_id = {i["id"]: i["status"] for i in data["items"]}
    assert status_by_id[c1.id] == 1
    assert status_by_id[c2.id] == 1
    assert status_by_id[c3.id] == 3  # 惰性过期展示
    assert status_by_id[c4.id] == 2

    # scope 过滤
    resp = await db_client.get("/api/coupon/list?scope=1", headers=authed["headers"])
    assert {i["id"] for i in resp.json()["data"]["items"]} == {c1.id, c3.id, c4.id}
    resp = await db_client.get("/api/coupon/list?scope=2", headers=authed["headers"])
    assert {i["id"] for i in resp.json()["data"]["items"]} == {c2.id}

    # status 过滤（1 未用排除已过期；3 过期含「未用但过有效期」；库内状态 1 不变）
    resp = await db_client.get("/api/coupon/list?status=1", headers=authed["headers"])
    assert {i["id"] for i in resp.json()["data"]["items"]} == {c1.id, c2.id}
    resp = await db_client.get("/api/coupon/list?status=3", headers=authed["headers"])
    assert {i["id"] for i in resp.json()["data"]["items"]} == {c3.id}
    resp = await db_client.get("/api/coupon/list?status=2", headers=authed["headers"])
    assert {i["id"] for i in resp.json()["data"]["items"]} == {c4.id}

    # 惰性过期不改库：c3 库内 status 仍为 1
    await db_session.refresh(c3)
    assert c3.status == 1


async def test_coupon_list_exposes_used_at_and_order_id(db_client, db_session, authed):
    """契约 additive 字段 used_at/order_id 必须进响应体：status=2 的三态靠它们区分。

    order_id 非空 + used_at 空 = 被订单锁定（尚可取消回滚），used_at 非空 = 真已核销；
    端点 `select(Coupon)` 直出 ORM 行、`CouponOut` 以 from_attributes 带出两列，
    本用例钉住这条链路（将来把查询改成显式投影时漏列会当场红）。
    """
    uid = authed["user_id"]
    now = datetime.now(UTC)
    unused = await _seed_coupon(db_session, uid)  # 未用：两者皆空
    locked = await _seed_coupon(db_session, uid, status=2, order_id=8801)  # 下单锁定未核销
    used = await _seed_coupon(
        db_session, uid, status=2, order_id=8802, used_at=now - timedelta(hours=1)
    )  # 已核销

    resp = await db_client.get("/api/coupon/list", headers=authed["headers"])
    assert resp.status_code == 200 and resp.json()["code"] == 0
    items = {i["id"]: i for i in resp.json()["data"]["items"]}
    assert set(items) >= {unused.id, locked.id, used.id}

    assert items[unused.id]["used_at"] is None and items[unused.id]["order_id"] is None
    assert items[locked.id]["status"] == 2
    assert items[locked.id]["order_id"] == 8801 and items[locked.id]["used_at"] is None
    assert items[used.id]["order_id"] == 8802
    used_at = datetime.fromisoformat(items[used.id]["used_at"])
    assert abs(used_at - (now - timedelta(hours=1))) < timedelta(seconds=5)
