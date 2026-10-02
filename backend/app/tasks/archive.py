"""记录按月分区归档任务（G8 / 04 §7.4「2 年记录按月分区归档」）。

职责：把源表中 `created_at` 早于「2 年前」的行**迁移**到对应的 `*_archive` 分区表：
1) 目标月份分区不存在时动态 `CREATE TABLE ... PARTITION OF ...`（左闭右开月界）；
2) `INSERT INTO archive (源列) SELECT 源列 FROM 源表 WHERE created_at < cutoff`（携带原 id
   与 created_at，`archived_at` 用默认 NOW()）；
3) `DELETE FROM 源表 WHERE created_at < cutoff`，热表只留近期数据。
全部在同一事务内完成，返回各表迁移行数。

源表 → 归档表映射（列与源表逐列对应，见 0010 迁移）：
    meal_record→meal_record_archive、sport_record→sport_record_archive、
    weight_record→weight_record_archive、step_record→step_record_archive、
    daily_snapshot→daily_snapshot_archive、track_event→track_event_archive、
    ai_dialog→ai_dialog_archive。

CLI（便于验证/补跑）：
    python -m app.tasks.archive --once
    python -m app.tasks.archive --once --years 2
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.session import get_sessionmaker

logger = get_logger(__name__)

# 源表 -> 归档分区父表
ARCHIVE_PAIRS: tuple[tuple[str, str], ...] = (
    ("meal_record", "meal_record_archive"),
    ("sport_record", "sport_record_archive"),
    ("weight_record", "weight_record_archive"),
    ("step_record", "step_record_archive"),
    ("daily_snapshot", "daily_snapshot_archive"),
    ("track_event", "track_event_archive"),
    ("ai_dialog", "ai_dialog_archive"),
)

DEFAULT_ARCHIVE_YEARS = 2


# 月界必须由 PG 侧计算：date_trunc 的返回值经驱动归一到 UTC，而在 Python 侧再
# .replace(day=1) 会落到上一个 UTC 月（+08 会话下必然错月），建出的分区盖不住目标行。
_MONTH_BOUNDS_SQL = """
    SELECT DISTINCT
        to_char(date_trunc('month', "created_at"), 'YYYY-MM-DD') AS month_start,
        to_char(date_trunc('month', "created_at") + interval '1 month', 'YYYY-MM-DD') AS month_end
"""


async def _common_columns(session: AsyncSession, source: str, archive: str) -> list[str]:
    """源表与归档表共有列（按源表顺序），用于 INSERT ... SELECT 的显式列清单。"""
    rows = (
        await session.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = :name
                ORDER BY ordinal_position
                """
            ),
            {"name": source},
        )
    ).all()
    src_cols = [r[0] for r in rows]
    arch = (
        await session.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = :name
                """
            ),
            {"name": archive},
        )
    ).all()
    arch_cols = {r[0] for r in arch}
    return [c for c in src_cols if c in arch_cols]


async def _ensure_partitions(
    session: AsyncSession, source: str, archive: str, cutoff: datetime
) -> None:
    """为源表中早于 cutoff 的行所在月份，按需创建归档月分区（已存在则跳过）。"""
    months = (
        await session.execute(
            text(f'{_MONTH_BOUNDS_SQL} FROM "{source}" WHERE "created_at" < :cutoff'),
            {"cutoff": cutoff},
        )
    ).all()
    for start, end in months:
        part = f"{archive}_{start[:4]}_{start[5:7]}"
        await session.execute(
            text(
                f'CREATE TABLE IF NOT EXISTS "{part}" PARTITION OF "{archive}" '
                f"FOR VALUES FROM ('{start}') TO ('{end}')"
            )
        )


async def _archive_table(
    session: AsyncSession, source: str, archive: str, cutoff: datetime
) -> int:
    """迁移单张源表：建分区 → INSERT SELECT → DELETE，返回迁移行数。"""
    await _ensure_partitions(session, source, archive, cutoff)
    cols = await _common_columns(session, source, archive)
    if not cols:
        return 0
    col_list = ", ".join(f'"{c}"' for c in cols)
    inserted = await session.execute(
        text(
            f'INSERT INTO "{archive}" ({col_list}) '
            f'SELECT {col_list} FROM "{source}" WHERE "created_at" < :cutoff'
        ),
        {"cutoff": cutoff},
    )
    await session.execute(
        text(f'DELETE FROM "{source}" WHERE "created_at" < :cutoff'),
        {"cutoff": cutoff},
    )
    return int(inserted.rowcount or 0)


async def archive_old_records(
    cutoff: datetime | None = None,
    *,
    years: int = DEFAULT_ARCHIVE_YEARS,
    session: AsyncSession | None = None,
) -> dict[str, int]:
    """把各源表中 `created_at` 早于 cutoff（默认「N 年前」，默认 2 年）的行迁入归档分区表。

    返回 `{源表名: 迁移行数}`。整体单事务：任一步失败则回滚（源表与归档表均不变）。
    未提供 session 时自建会话并负责关闭。
    """
    if cutoff is None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=365 * years)

    own_session = session is None
    if own_session:
        session = get_sessionmaker()()
    assert session is not None

    counts: dict[str, int] = {}
    try:
        for source, archive in ARCHIVE_PAIRS:
            counts[source] = await _archive_table(session, source, archive, cutoff)
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        if own_session:
            await session.close()

    logger.info("归档任务完成", extra={"cutoff": cutoff.isoformat(), "counts": counts})
    return counts


def main(argv: list[str] | None = None) -> int:
    """CLI 入口：按 --years 立即执行一次归档。"""
    parser = argparse.ArgumentParser(description="记录按月分区归档任务（G8）")
    parser.add_argument("--once", action="store_true", help="立即执行一次归档")
    parser.add_argument(
        "--years", type=int, default=DEFAULT_ARCHIVE_YEARS, help="保留年限阈值（默认 2）"
    )
    args = parser.parse_args(argv)

    counts = asyncio.run(archive_old_records(years=args.years))
    total = sum(counts.values())
    for table, n in counts.items():
        print(f"{table}: 归档 {n} 行")
    print(f"归档完成：共 {total} 行")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())