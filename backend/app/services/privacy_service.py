"""隐私设置服务（openapi: /api/privacy GET / PUT）。

`user_privacy` 一人一条，读取/更新均惰性建行（INSERT ... ON CONFLICT DO NOTHING）。
默认值：anonymous=true、mask_share=true、可见性=1（公开）、allow_data_export=true。
DB 可见性列为 SMALLINT(1/0)，契约 PrivacyData 为 bool，此处做双向映射。
PUT 支持部分字段（仅更新非 None 的传参）。
"""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UserPrivacy
from app.schemas.privacy import PrivacyData, PrivacyIn

# 契约字段 → DB 列（visibility_* 为 bool→smallint）
_BOOL_FIELDS = ("anonymous", "mask_share", "allow_data_export")
_VISIBILITY_FIELDS = ("visibility_leaderboard", "visibility_community")


def _to_data(row: UserPrivacy) -> PrivacyData:
    """DB 行 → 契约结构（可见性 smallint→bool）。"""
    return PrivacyData(
        anonymous=bool(row.anonymous),
        mask_share=bool(row.mask_share),
        visibility_leaderboard=bool(row.visibility_leaderboard),
        visibility_community=bool(row.visibility_community),
        allow_data_export=bool(row.allow_data_export),
    )


async def _ensure_row(session: AsyncSession, *, user_id: int) -> UserPrivacy:
    """惰性建行并返回（默认值由 DB server_default 提供）。"""
    await session.execute(
        pg_insert(UserPrivacy)
        .values(user_id=user_id)
        .on_conflict_do_nothing(index_elements=["user_id"])
    )
    await session.commit()
    return (
        await session.execute(select(UserPrivacy).where(UserPrivacy.user_id == user_id))
    ).scalar_one()


async def get_privacy(session: AsyncSession, *, user_id: int) -> PrivacyData:
    """返回用户当前隐私设置（缺省行惰性创建）。"""
    return _to_data(await _ensure_row(session, user_id=user_id))


async def update_privacy(
    session: AsyncSession, *, user_id: int, payload: PrivacyIn
) -> PrivacyData:
    """部分更新隐私设置，返回更新后的完整设置。"""
    row = await _ensure_row(session, user_id=user_id)
    for field in _BOOL_FIELDS:
        value = getattr(payload, field)
        if value is not None:
            setattr(row, field, value)
    for field in _VISIBILITY_FIELDS:
        value = getattr(payload, field)
        if value is not None:
            setattr(row, field, 1 if value else 0)
    await session.commit()
    await session.refresh(row)
    return _to_data(row)