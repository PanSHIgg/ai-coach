"""隐私设置测试（G3）：默认值 + 惰性建行、部分字段更新、可见性 bool↔smallint 映射。"""

import pytest
from sqlalchemy import select

from app.models import UserPrivacy

_DEFAULTS = {
    "anonymous": True,
    "mask_share": True,
    "visibility_leaderboard": True,
    "visibility_community": True,
    "allow_data_export": True,
}


async def test_privacy_defaults_then_partial_update(db_client, db_session, authed):
    data = (await db_client.get("/api/privacy", headers=authed["headers"])).json()["data"]
    assert data == _DEFAULTS
    # 读取即惰性建行
    row = await db_session.scalar(
        select(UserPrivacy).where(UserPrivacy.user_id == authed["user_id"])
    )
    assert row is not None

    updated = (
        await db_client.put(
            "/api/privacy",
            headers=authed["headers"],
            json={"anonymous": False, "allow_data_export": False},
        )
    ).json()["data"]
    assert updated["anonymous"] is False
    assert updated["allow_data_export"] is False
    # 未传字段保持原值
    assert updated["mask_share"] is True
    assert updated["visibility_leaderboard"] is True
    assert updated["visibility_community"] is True


@pytest.mark.parametrize(
    "field,value,expected",
    [
        ("visibility_leaderboard", False, 0),
        ("visibility_community", False, 0),
        ("visibility_leaderboard", True, 1),
    ],
)
async def test_privacy_visibility_maps_to_smallint(
    db_client, db_session, authed, field, value, expected
):
    data = (
        await db_client.put("/api/privacy", headers=authed["headers"], json={field: value})
    ).json()["data"]
    assert data[field] is value
    row = await db_session.scalar(
        select(UserPrivacy).where(UserPrivacy.user_id == authed["user_id"])
    )
    assert getattr(row, field) == expected