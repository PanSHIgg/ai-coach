"""埋点上报接口测试（F3）：POST /api/track。

覆盖六类行为（每类一个独立用例）：匿名落库（user_id IS NULL）、带 token 关联用户、
occurred_at 缺省走服务端时间、occurred_at 显式落库、元数据落库、参数边界。
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import TrackEvent

TZ = timezone(timedelta(hours=8))


async def _rows(session) -> list[TrackEvent]:
    """按写入顺序读取落库的埋点行。"""
    return list((await session.execute(select(TrackEvent).order_by(TrackEvent.id))).scalars().all())


async def test_anonymous_report_persists_null_user(db_client, db_session):
    resp = await db_client.post(
        "/api/track", json={"events": [{"event": "scan_in"}, {"event": "login"}]}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["accepted"] == 2

    rows = await _rows(db_session)
    assert len(rows) == 2
    assert all(r.user_id is None for r in rows)


async def test_token_report_associates_user(db_client, db_session, authed):
    resp = await db_client.post(
        "/api/track",
        json={"events": [{"event": "login"}]},
        headers=authed["headers"],
    )
    assert resp.status_code == 200
    assert [r.user_id for r in await _rows(db_session)] == [authed["user_id"]]


async def test_occurred_at_defaults_to_server_time(db_client, db_session):
    resp = await db_client.post("/api/track", json={"events": [{"event": "login"}]})
    assert resp.status_code == 200
    row = (await _rows(db_session))[0]
    assert row.occurred_at is not None


async def test_occurred_at_explicit_is_persisted(db_client, db_session):
    occurred = datetime(2026, 1, 2, 3, 4, 5, tzinfo=TZ)
    resp = await db_client.post(
        "/api/track",
        json={"events": [{"event": "login", "occurred_at": occurred.isoformat()}]},
    )
    assert resp.status_code == 200
    assert (await _rows(db_session))[0].occurred_at == occurred


async def test_metadata_device_platform_properties_persisted(db_client, db_session):
    resp = await db_client.post(
        "/api/track",
        json={
            "events": [{"event": "order_pay", "properties": {"amount": 29.9, "sku": "A1"}}],
            "device_id": "dev-abc",
            "platform": 2,
        },
    )
    assert resp.status_code == 200
    row = (await _rows(db_session))[0]
    assert row.device_id == "dev-abc"
    assert row.platform == 2
    assert row.properties == {"amount": 29.9, "sku": "A1"}


async def test_platform_defaults_to_1(db_client, db_session):
    resp = await db_client.post("/api/track", json={"events": [{"event": "login"}]})
    assert resp.status_code == 200
    assert (await _rows(db_session))[0].platform == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"events": []},
        {"events": [{"event": "e"}] * 51},
        {"events": [{"event": "x" * 65}]},
    ],
    ids=["empty-events", "over-50-events", "event-name-over-64"],
)
async def test_invalid_payload_returns_422_2001(db_client, payload):
    resp = await db_client.post("/api/track", json=payload)
    assert resp.status_code == 422
    assert resp.json()["code"] == 2001
