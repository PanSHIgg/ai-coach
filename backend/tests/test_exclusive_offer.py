"""专属优惠（异业联盟券）测试（G3）。

覆盖：仅返回上架（status=1）且未过期（valid_to 为空或未到）的 exclusive_offer，
并映射契约 CouponOut（scope 恒为 3 异业）。
"""

from datetime import datetime, timedelta, timezone

from app.models import ExclusiveOffer

TZ = timezone(timedelta(hours=8))


async def test_exclusive_lists_only_active_and_unexpired(db_client, db_session, authed):
    now = datetime.now(TZ)
    offers = [
        ExclusiveOffer(
            title="养生馆体验券", category="养生", partner="A", coupon_amount=0, status=1, valid_to=None
        ),
        ExclusiveOffer(
            title="抵50元券",
            category="食品",
            partner="B",
            coupon_amount=50,
            status=1,
            valid_to=now + timedelta(days=10),
        ),
        ExclusiveOffer(
            title="已过期券",
            category="洗护",
            partner="C",
            coupon_amount=10,
            status=1,
            valid_to=now - timedelta(days=1),
        ),
        ExclusiveOffer(
            title="已下架券",
            category="运动",
            partner="D",
            coupon_amount=20,
            status=0,
            valid_to=now + timedelta(days=10),
        ),
    ]
    db_session.add_all(offers)
    await db_session.commit()

    data = (await db_client.get("/api/coupon/exclusive", headers=authed["headers"])).json()["data"]
    items = data["items"]
    assert {it["id"] for it in items} == {offers[0].id, offers[1].id}
    assert all(it["scope"] == 3 and it["status"] == 1 for it in items)

    free = next(it for it in items if it["id"] == offers[0].id)
    assert (free["type"], free["amount"], free["valid_to"]) == (3, 0.0, None)
    paid = next(it for it in items if it["id"] == offers[1].id)
    assert (paid["type"], paid["amount"]) == (1, 50.0)
    assert paid["valid_to"] is not None