"""商家域测试（BE5 Phase 3）：LBS 列表、详情、标准目录。

真实 DB（db_client + db_session + authed）；sku_catalog 为参照数据（5 行种子：
FD-001/002/003、SP-001/002）不被清空。
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.models import Merchant, MerchantSku, RedeemLog
from app.services import merchant_service

TZ = timezone(timedelta(hours=8))

# 上海人民广场附近两点（直线约 1.1km）
_LAT1, _LNG1 = 31.2304, 121.4737
_LAT2, _LNG2 = 31.2230, 121.4820


async def _seed_merchant(
    db_session,
    name="轻食一号店",
    *,
    category="轻食",
    lat=None,
    lng=None,
    status=1,
    audit_status=1,
    rating=4.8,
    created_at=None,
) -> Merchant:
    m = Merchant(
        name=name,
        category=category,
        address="XX路1号",
        lat=lat,
        lng=lng,
        rating=rating,
        status=status,
        audit_status=audit_status,
        created_at=created_at or datetime.now(TZ),
    )
    db_session.add(m)
    await db_session.commit()
    return m


async def _seed_sku(db_session, merchant_id: int, catalog_id: int, price=28.0, stock=99, status=1):
    ms = MerchantSku(merchant_id=merchant_id, catalog_id=catalog_id, price=price, stock=stock, status=status)
    db_session.add(ms)
    await db_session.commit()
    return ms


async def test_list_returns_briefs_with_distance(db_client, db_session, authed):
    """列表：只出过审营业商家；带坐标返回距离与结构。"""
    now = datetime.now(TZ)
    # 拉新分【假设】：创建时间新→旧归一化；远店更晚创建 → 权重分更高排前
    m1 = await _seed_merchant(db_session, "近店", lat=_LAT1, lng=_LNG1, created_at=now - timedelta(minutes=1))
    await _seed_sku(db_session, m1.id, 1)
    await _seed_merchant(db_session, "远店", lat=_LAT1 + 0.005, lng=_LNG1 + 0.005, created_at=now)
    await _seed_merchant(db_session, "待审店", lat=_LAT1, lng=_LNG1, audit_status=0)
    await _seed_merchant(db_session, "停业店", lat=_LAT1, lng=_LNG1, status=0)
    await db_session.commit()

    resp = await db_client.get(
        "/api/merchant/list", headers=authed["headers"], params={"lat": _LAT2, "lng": _LNG2}
    )
    body = resp.json()

    assert resp.status_code == 200
    assert body["code"] == 0
    names = [it["name"] for it in body["data"]["items"]]
    # 待审/停业不出现；权重排序【假设】拉新分生效：远店创建更晚 → 排前
    assert names == ["远店", "近店"]
    item = body["data"]["items"][0]
    assert set(item) >= {
        "id", "name", "category", "distance_m", "rating", "status", "partner_level",
    }
    assert item["partner_level"] == 0  # 默认普通商家（R-01）
    assert item["distance_m"] > 0 and isinstance(item["distance_m"], int)
    assert item["rating"] == 4.8
    assert body["data"]["page"]["total"] == 2
    assert body["data"]["page"]["page_size"] == 20


@pytest.mark.parametrize(
    "radius, expect_visible",
    [(1500, True), (500, False)],
    ids=["in-radius", "out-of-radius"],
)
async def test_list_radius_filter(db_client, db_session, authed, radius, expect_visible):
    """列表：distance_m 超出 radius 不返回。"""
    await _seed_merchant(db_session, "附近店", lat=_LAT1, lng=_LNG1)
    await db_session.commit()

    resp = await db_client.get(
        "/api/merchant/list",
        headers=authed["headers"],
        params={"lat": _LAT2, "lng": _LNG2, "radius": radius},
    )
    body = resp.json()

    assert resp.status_code == 200 and body["code"] == 0
    if expect_visible:
        assert body["data"]["page"]["total"] == 1
    else:
        assert body["data"]["page"]["total"] == 0
        assert body["data"]["items"] == []


async def test_list_category_filter(db_client, db_session, authed):
    """列表：category 精确过滤。"""
    await _seed_merchant(db_session, "轻食店", category="轻食")
    await _seed_merchant(db_session, "便利店", category="便利店")
    await db_session.commit()

    resp = await db_client.get(
        "/api/merchant/list", headers=authed["headers"], params={"category": "便利店"}
    )
    body = resp.json()

    assert resp.status_code == 200 and body["code"] == 0
    assert [it["name"] for it in body["data"]["items"]] == ["便利店"]


async def test_list_without_geo_sorted_by_id(db_client, db_session, authed):
    """列表：不传坐标也返回（按 id 升序，distance_m=None）。"""
    m1 = await _seed_merchant(db_session, "甲店")
    m2 = await _seed_merchant(db_session, "乙店")
    await db_session.commit()

    resp = await db_client.get("/api/merchant/list", headers=authed["headers"])
    body = resp.json()

    assert resp.status_code == 200 and body["code"] == 0
    assert [it["id"] for it in body["data"]["items"]] == [m1.id, m2.id]
    assert all(it["distance_m"] is None for it in body["data"]["items"])


async def test_list_null_coords_merchant_no_500(db_client, db_session, authed):
    """P1-2：lat/lng 为 NULL 的商家 + 带坐标查询 → 200 不 500，distance_m=None。"""
    m_null = await _seed_merchant(db_session, "无坐标店")  # lat/lng 默认 None
    m_geo = await _seed_merchant(db_session, "有坐标店", lat=_LAT1, lng=_LNG1)
    await db_session.commit()

    resp = await db_client.get(
        "/api/merchant/list", headers=authed["headers"], params={"lat": _LAT2, "lng": _LNG2}
    )
    body = resp.json()

    assert resp.status_code == 200 and body["code"] == 0
    by_id = {it["id"]: it for it in body["data"]["items"]}
    assert by_id[m_null.id]["distance_m"] is None  # 与 detail 路径同口径
    assert by_id[m_geo.id]["distance_m"] is not None


async def test_detail_contains_skus(db_client, db_session, authed):
    """详情：merchant 字段 + status=1 的 merchant_sku join catalog 得 skus；带坐标含距离。"""
    from sqlalchemy import select

    from app.models import SkuCatalog

    seeds = (await db_session.scalars(select(SkuCatalog).order_by(SkuCatalog.id).limit(2))).all()
    m = await _seed_merchant(db_session, "详情店", lat=_LAT1, lng=_LNG1)
    ms_off = await _seed_sku(db_session, m.id, seeds[0].id, price=25.5, stock=50)
    await _seed_sku(db_session, m.id, seeds[1].id, price=18.0, stock=-1)
    ms_off.status = 0  # 下架不出（uk_ms 限制同店同目录唯一，用 update 造下架）
    await db_session.commit()

    resp = await db_client.get(
        f"/api/merchant/{m.id}", headers=authed["headers"], params={"lat": _LAT2, "lng": _LNG2}
    )
    body = resp.json()

    assert resp.status_code == 200 and body["code"] == 0
    data = body["data"]
    assert data["id"] == m.id and data["name"] == "详情店"
    assert data["distance_m"] > 0
    # ms_off（25.5 元）被下架不出；-1 表示不限量
    assert len(data["skus"]) == 1
    assert data["skus"][0]["price"] == 18.0 and data["skus"][0]["stock"] == -1
    assert isinstance(data["lat"], float) and isinstance(data["lng"], float)
    assert data["partner_level"] == 0  # 合作层级默认普通（R-01）


@pytest.mark.parametrize(
    "seed_kwargs, expect_code, expect_status",
    [
        (None, 3001, 404),
        ({"status": 0}, 5001, 409),
    ],
    ids=["not-found", "closed"],
)
async def test_detail_error_cases(
    db_client, db_session, authed, seed_kwargs, expect_code, expect_status
):
    """详情：不存在 3001/404；status=0 停业 5001/409。【假设】停业返回 5001。"""
    merchant_id = 99999
    if seed_kwargs is not None:
        m = await _seed_merchant(db_session, "停业店", **seed_kwargs)
        merchant_id = m.id

    resp = await db_client.get(f"/api/merchant/{merchant_id}", headers=authed["headers"])
    body = resp.json()

    assert resp.status_code == expect_status
    assert body["code"] == expect_code
    assert body["data"] is None


async def test_sku_catalog_returns_seed_with_price_range(db_client, authed):
    """目录：5 行种子 + min/max 限价区间字段；category 过滤生效。"""
    resp = await db_client.get("/api/sku/catalog", headers=authed["headers"])
    body = resp.json()

    assert resp.status_code == 200 and body["code"] == 0
    items = body["data"]["items"]
    assert len(items) == 5
    codes = {it["code"] for it in items}
    assert codes == {"FD-001", "FD-002", "FD-003", "SP-001", "SP-002"}
    for it in items:
        assert it["min_price"] <= it["base_price"] <= it["max_price"]
        assert {"calories_low", "calories_high", "unit"} <= set(it)

    resp2 = await db_client.get(
        "/api/sku/catalog", headers=authed["headers"], params={"category": "标准减脂餐"}
    )
    body2 = resp2.json()
    assert resp2.status_code == 200 and body2["code"] == 0
    assert len(body2["data"]["items"]) == 3
    assert {it["category"] for it in body2["data"]["items"]} == {"标准减脂餐"}


# ---------------------------------------------------------------------------
# R-01：权重保护 / 清退（§6.3.4）
# ---------------------------------------------------------------------------


async def test_partner_levels_ranking_bands(db_session):
    """排名分档：5 家同质商家（仅创建时间递减）→ 前 20% 战略 / 前 50% 优选 / 其余普通。"""
    now = datetime.now(TZ)
    ms = [
        await _seed_merchant(db_session, f"M{i}", rating=5.0, created_at=now - timedelta(minutes=i))
        for i in range(5)
    ]
    await db_session.commit()

    levels = await merchant_service.evaluate_partner_levels(db_session)
    # 权重分降序 = 创建时间新→旧 = id 升序；ceil(0.2*5)=1、ceil(0.5*5)=3
    assert [levels[m.id] for m in ms] == [2, 1, 1, 0, 0]


async def test_partner_levels_ranking_monotonic(db_session):
    """单调性：10 家 → 名次越靠前层级越高（2/1/0 非递增），不出现低分高档。"""
    now = datetime.now(TZ)
    ms = [
        await _seed_merchant(db_session, f"K{i}", rating=5.0, created_at=now - timedelta(minutes=i))
        for i in range(10)
    ]
    await db_session.commit()

    levels = await merchant_service.evaluate_partner_levels(db_session)
    ordered = [levels[m.id] for m in ms]
    # ceil(0.2*10)=2、ceil(0.5*10)=5
    assert ordered == [2, 2, 1, 1, 1, 0, 0, 0, 0, 0]
    assert ordered == sorted(ordered, reverse=True)  # 单调不递增


async def test_zero_contribution_eviction_and_no_false_eviction(db_session):
    """零贡献清退：建店满窗口且近 N 天无成功核销 → 清退；有核销/新店不误伤。"""
    now = datetime.now(TZ)
    old = now - timedelta(days=30)
    aged = await _seed_merchant(db_session, "沉默老店", created_at=old)
    active = await _seed_merchant(db_session, "活跃老店", created_at=old)
    newbie = await _seed_merchant(db_session, "新店", created_at=now)
    db_session.add(
        RedeemLog(merchant_id=active.id, result=1, created_at=now - timedelta(days=1))
    )
    await db_session.commit()

    evicted = await merchant_service.evict_zero_contribution(db_session)
    assert evicted == [aged.id]

    from sqlalchemy import select

    rows = {m.id: m for m in (await db_session.scalars(select(Merchant))).all()}
    assert rows[aged.id].status == 0 and rows[aged.id].partner_level == 0  # 已清退
    assert rows[active.id].status == 1  # 有贡献不清退
    assert rows[active.id].last_contribution_at is not None  # 回填最近贡献时间
    assert rows[newbie.id].status == 1  # 新店（未满窗口）不清退
    assert rows[newbie.id].last_contribution_at is None
