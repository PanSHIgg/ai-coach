"""体重记录服务（BE-w）：CRUD + 趋势。

默认决策 / 假设：
- record_at 缺省当日（UTC+8），source 缺省 1（手动）。
- 新增后【假设】同步 body_profile.current_weight：仅当该记录为「最新日期」记录时更新
  （避免补录历史数据把当前体重改旧）；无档案则跳过同步、不自动建档。
- 列表分页按 record_at DESC；趋势【假设】缺省最近 30 天，按 record_at 升序返回，
  同日多条取当日最后一条（created_at/id 最大）。
- 行级隔离：查询/删除带 user_id，越权/不存在统一 3001。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppException
from app.models import BodyProfile, WeightRecord
from app.schemas.common import ErrorCode, PageMeta
from app.schemas.weight import (
    WeightDeleteData,
    WeightPageData,
    WeightRecordOut,
    WeightTrendData,
    WeightTrendItem,
)

TZ = timezone(timedelta(hours=8))
TREND_DEFAULT_DAYS = 30


def today_tz() -> date:
    return datetime.now(TZ).date()


def _weight_out(record: WeightRecord) -> WeightRecordOut:
    return WeightRecordOut(
        id=record.id,
        weight=float(record.weight),
        record_at=record.record_at,
        source=int(record.source) if record.source is not None else None,
        note=record.note,
        created_at=record.created_at,
    )


async def list_weights(
    session: AsyncSession, user_id: int, page: int = 1, page_size: int = 20
) -> WeightPageData:
    """体重记录分页（行级隔离，record_at DESC）。"""
    total = await session.scalar(
        select(func.count()).select_from(WeightRecord).where(WeightRecord.user_id == user_id)
    )
    rows = (
        (
            await session.execute(
                select(WeightRecord)
                .where(WeightRecord.user_id == user_id)
                .order_by(
                    WeightRecord.record_at.desc(),
                    WeightRecord.created_at.desc(),
                    WeightRecord.id.desc(),
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return WeightPageData(
        items=[_weight_out(r) for r in rows],
        page=PageMeta(page=page, page_size=page_size, total=int(total or 0)),
    )


async def _sync_profile_weight(session: AsyncSession, user_id: int, record: WeightRecord) -> None:
    """若该记录为最新日期记录，则同步 body_profile.current_weight。"""
    latest = (
        await session.execute(
            select(WeightRecord)
            .where(WeightRecord.user_id == user_id)
            .order_by(
                WeightRecord.record_at.desc(),
                WeightRecord.created_at.desc(),
                WeightRecord.id.desc(),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if latest is None or latest.id != record.id:
        return
    profile = (
        await session.execute(select(BodyProfile).where(BodyProfile.user_id == user_id))
    ).scalar_one_or_none()
    if profile is not None:
        profile.current_weight = record.weight


async def _recompute_profile_weight(session: AsyncSession, user_id: int) -> None:
    """删除后按最新一条体重记录重算并回写档案当前体重（与新增逻辑对称）。

    若已无任何体重记录，则保持现档案值（不置空、不回退默认），避免删掉最后一条记录
    把 current_weight 清空。
    """
    latest = (
        await session.execute(
            select(WeightRecord)
            .where(WeightRecord.user_id == user_id)
            .order_by(
                WeightRecord.record_at.desc(),
                WeightRecord.created_at.desc(),
                WeightRecord.id.desc(),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    profile = (
        await session.execute(select(BodyProfile).where(BodyProfile.user_id == user_id))
    ).scalar_one_or_none()
    if profile is None or latest is None:
        return
    profile.current_weight = latest.weight


async def create_weight(session: AsyncSession, user_id: int, payload) -> WeightRecordOut:
    """新增体重记录；最新日期记录同步档案当前体重。"""
    record = WeightRecord(
        user_id=user_id,
        weight=payload.weight,
        record_at=payload.record_at or today_tz(),
        source=payload.source if payload.source is not None else 1,
        note=payload.note,
    )
    session.add(record)
    await session.flush()
    await _sync_profile_weight(session, user_id, record)
    await session.commit()
    return _weight_out(record)


async def delete_weight(session: AsyncSession, user_id: int, weight_id: int) -> WeightDeleteData:
    """行级隔离删除体重记录；不存在/越权 → 3001。"""
    record = (
        await session.execute(
            select(WeightRecord).where(
                WeightRecord.id == weight_id, WeightRecord.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if record is None:
        raise AppException(ErrorCode.NOT_FOUND, "体重记录不存在")
    await session.execute(delete(WeightRecord).where(WeightRecord.id == weight_id))
    await session.flush()
    # 删除后按剩余最新一条记录重算档案当前体重（无记录则保持现档案值）
    await _recompute_profile_weight(session, user_id)
    await session.commit()
    return WeightDeleteData(id=weight_id, deleted=True)


async def get_trend(
    session: AsyncSession,
    user_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
) -> WeightTrendData:
    """体重趋势：【假设】缺省最近 30 天，按 record_at 升序；同日取最后一条。"""
    end = end_date or today_tz()
    start = start_date or (end - timedelta(days=TREND_DEFAULT_DAYS - 1))
    rows = (
        (
            await session.execute(
                select(WeightRecord)
                .where(
                    WeightRecord.user_id == user_id,
                    WeightRecord.record_at >= start,
                    WeightRecord.record_at <= end,
                )
                .order_by(
                    WeightRecord.record_at.asc(),
                    WeightRecord.created_at.asc(),
                    WeightRecord.id.asc(),
                )
            )
        )
        .scalars()
        .all()
    )
    # 同日多条 → 保留最后一条
    by_day: dict[date, WeightRecord] = {}
    for r in rows:
        by_day[r.record_at] = r
    items = [
        WeightTrendItem(date=d, weight=float(r.weight))
        for d, r in sorted(by_day.items(), key=lambda kv: kv[0])
    ]
    start_weight = items[0].weight if items else None
    latest_weight = items[-1].weight if items else None
    change = round(latest_weight - start_weight, 1) if items else None
    return WeightTrendData(
        items=items, start_weight=start_weight, latest_weight=latest_weight, change=change
    )
