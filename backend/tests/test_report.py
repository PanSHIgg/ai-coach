"""报告导出与周报测试（G3 报告导出 / G12 周报）。

覆盖：体重 CSV 导出 + report_export 落库、周报聚合（摄入/缺口/步数均值 + 体重变化 + AI 点评含免责声明）、
空数据零值、周报 CSV 导出。
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.ai.prompts import AI_DISCLAIMER
from app.models import DailySnapshot, ReportExport, WeightRecord

TZ = timezone(timedelta(hours=8))


async def test_export_weight_csv_and_record(db_client, db_session, authed):
    uid = authed["user_id"]
    today = datetime.now(TZ).date()
    db_session.add_all(
        [
            WeightRecord(user_id=uid, weight=68.5, record_at=today),
            WeightRecord(user_id=uid, weight=70.0, record_at=today - timedelta(days=1)),
        ]
    )
    await db_session.commit()

    data = (
        await db_client.post(
            "/api/report/export",
            headers=authed["headers"],
            json={"report_type": "weight", "format": "csv"},
        )
    ).json()["data"]
    assert data["mime"] == "text/csv"
    assert data["filename"].endswith(".csv")
    lines = data["content"].strip().split("\n")
    assert lines[0] == "date,weight,source,note"
    # record_at 升序
    assert lines[1].startswith((today - timedelta(days=1)).isoformat())
    assert lines[2].startswith(today.isoformat())

    rec = await db_session.scalar(select(ReportExport).where(ReportExport.user_id == uid))
    assert rec is not None
    assert (rec.report_type, rec.format) == ("weight", "csv")
    assert rec.content == data["content"]
    assert rec.expires_at is not None


async def test_weekly_report_aggregates_and_comment(db_client, db_session, authed):
    uid = authed["user_id"]
    today = datetime.now(TZ).date()
    monday = today - timedelta(days=today.weekday())
    db_session.add_all(
        [
            DailySnapshot(user_id=uid, snapshot_date=monday, intake=1600, deficit=-400, steps=8000),
            DailySnapshot(
                user_id=uid,
                snapshot_date=monday + timedelta(days=1),
                intake=1400,
                deficit=-600,
                steps=10000,
            ),
            WeightRecord(user_id=uid, weight=70.0, record_at=monday),
            WeightRecord(user_id=uid, weight=69.3, record_at=monday + timedelta(days=1)),
        ]
    )
    await db_session.commit()

    data = (await db_client.get("/api/report/weekly", headers=authed["headers"])).json()["data"]
    assert data["period"] == {
        "start": monday.isoformat(),
        "end": (monday + timedelta(days=6)).isoformat(),
    }
    assert data["intake_avg"] == 1500.0
    assert data["deficit_avg"] == -500.0
    assert data["steps_avg"] == 9000
    assert data["weight_change"] == -0.7
    assert AI_DISCLAIMER in data["comment"]
    assert [d["date"] for d in data["days"]] == [
        monday.isoformat(),
        (monday + timedelta(days=1)).isoformat(),
    ]
    assert data["days"][0]["weight"] == 70.0
    assert data["days"][1]["intake"] == 1400.0


async def test_weekly_report_empty_is_zero_and_none(db_client, authed):
    data = (await db_client.get("/api/report/weekly", headers=authed["headers"])).json()["data"]
    assert (data["intake_avg"], data["deficit_avg"], data["steps_avg"]) == (0, 0, 0)
    assert data["weight_change"] is None
    assert data["days"] == []
    assert AI_DISCLAIMER in data["comment"]


async def test_export_weekly_csv(db_client, db_session, authed):
    uid = authed["user_id"]
    today = datetime.now(TZ).date()
    db_session.add(
        DailySnapshot(user_id=uid, snapshot_date=today, intake=1500, deficit=-500, steps=9000)
    )
    await db_session.commit()

    data = (
        await db_client.post(
            "/api/report/export",
            headers=authed["headers"],
            json={"report_type": "weekly", "format": "csv"},
        )
    ).json()["data"]
    assert data["mime"] == "text/csv"
    lines = data["content"].strip().split("\n")
    assert lines[0] == "date,intake,deficit,steps,weight"
    assert lines[1].startswith(today.isoformat())