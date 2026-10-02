"""报告服务（openapi: /api/report/export、/api/report/weekly）。

- export：weight → 体重记录 CSV；weekly → 周报 days CSV；插入 `report_export`（含过期时间），
  返回 {filename, mime:"text/csv", content}；
- weekly：聚合周期内 `daily_snapshot`（摄入/缺口/步数）+ `weight_record`（体重变化），
  点评**优先复用** `ai_service.weekly_comment`（无 LLM Key 时其内部降级为确定性模板 + 免责声明）。

周号口径复用 `ai_service._week_range`（UTC+8，缺省取本周）。
"""

import csv
import io
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DailySnapshot, ReportExport, WeightRecord
from app.schemas.report import (
    ReportExportData,
    ReportExportIn,
    WeeklyReportData,
    WeeklyReportDay,
    WeeklyReportPeriod,
)
from app.services import ai_service

TZ = timezone(timedelta(hours=8))
EXPORT_TTL_DAYS = 7
MIME_CSV = "text/csv"


def _csv_text(header: list[str], rows: list[list]) -> str:
    """CSV 文本（统一 `\\n` 行尾，便于前端落盘与断言）。"""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buf.getvalue()


async def _weight_csv(session: AsyncSession, *, user_id: int) -> str:
    rows = (
        await session.scalars(
            select(WeightRecord)
            .where(WeightRecord.user_id == user_id)
            .order_by(WeightRecord.record_at.asc(), WeightRecord.id.asc())
        )
    ).all()
    return _csv_text(
        ["date", "weight", "source", "note"],
        [
            [r.record_at.isoformat(), float(r.weight), int(r.source), r.note or ""]
            for r in rows
        ],
    )


async def export_report(
    session: AsyncSession, *, user_id: int, payload: ReportExportIn
) -> ReportExportData:
    """导出报告（首期 csv），返回 filename/mime/content。"""
    now = datetime.now(TZ)
    if payload.report_type == "weight":
        content = await _weight_csv(session, user_id=user_id)
    else:  # weekly
        report = await weekly_report(session, user_id=user_id, week=None)
        content = _csv_text(
            ["date", "intake", "deficit", "steps", "weight"],
            [
                [
                    d.date.isoformat(),
                    "" if d.intake is None else d.intake,
                    "" if d.deficit is None else d.deficit,
                    "" if d.steps is None else d.steps,
                    "" if d.weight is None else d.weight,
                ]
                for d in report.days
            ],
        )
    filename = f"{payload.report_type}_{now.date().isoformat()}.csv"
    session.add(
        ReportExport(
            user_id=user_id,
            report_type=payload.report_type,
            format=payload.format,
            filename=filename,
            content=content,
            expires_at=now + timedelta(days=EXPORT_TTL_DAYS),
        )
    )
    await session.commit()
    return ReportExportData(filename=filename, mime=MIME_CSV, content=content)


async def weekly_report(
    session: AsyncSession, *, user_id: int, week: str | None
) -> WeeklyReportData:
    """返回热量控制周报（period/intake_avg/deficit_avg/steps_avg/weight_change/comment/days）。"""
    _key, start, end = ai_service._week_range(week)

    snapshots = (
        await session.scalars(
            select(DailySnapshot)
            .where(
                DailySnapshot.user_id == user_id,
                DailySnapshot.snapshot_date >= start,
                DailySnapshot.snapshot_date <= end,
            )
            .order_by(DailySnapshot.snapshot_date)
        )
    ).all()
    weights = (
        await session.scalars(
            select(WeightRecord)
            .where(
                WeightRecord.user_id == user_id,
                WeightRecord.record_at >= start,
                WeightRecord.record_at <= end,
            )
            .order_by(WeightRecord.record_at.asc(), WeightRecord.id.asc())
        )
    ).all()

    snap_by_date = {s.snapshot_date: s for s in snapshots}
    weight_by_date = {w.record_at: w for w in weights}  # 同日取最后一条（升序遍历覆盖）
    days = [
        WeeklyReportDay(
            date=d,
            intake=float(snap_by_date[d].intake) if d in snap_by_date else None,
            deficit=float(snap_by_date[d].deficit) if d in snap_by_date else None,
            steps=int(snap_by_date[d].steps) if d in snap_by_date else None,
            weight=float(weight_by_date[d].weight) if d in weight_by_date else None,
        )
        for d in sorted(set(snap_by_date) | set(weight_by_date))
    ]

    n = len(snapshots)
    intake_avg = round(sum(float(s.intake or 0) for s in snapshots) / n, 1) if n else 0.0
    deficit_avg = round(sum(float(s.deficit or 0) for s in snapshots) / n, 1) if n else 0.0
    steps_avg = int(round(sum(int(s.steps or 0) for s in snapshots) / n)) if n else 0
    weight_change = (
        round(float(weights[-1].weight) - float(weights[0].weight), 1) if len(weights) >= 2 else None
    )

    comment = (await ai_service.weekly_comment(session, user_id=user_id, week=week)).content

    return WeeklyReportData(
        period=WeeklyReportPeriod(start=start, end=end),
        intake_avg=intake_avg,
        deficit_avg=deficit_avg,
        steps_avg=steps_avg,
        weight_change=weight_change,
        comment=comment,
        days=days,
    )