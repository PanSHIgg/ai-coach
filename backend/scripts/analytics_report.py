#!/usr/bin/env python3
"""F3 核心指标聚合报表（docs/split/01-整体架构与产品需求.md §1.6 的 6 项指标）。

用法：
    python backend/scripts/analytics_report.py \
        --dsn "postgresql://postgres:postgres@127.0.0.1:5432/ai_coach"

口径与就绪度原则：
- 能从现有表（user.created_at / invite / track_event）真算的指标就真算；
- 数据源缺失的指标 **显式返回 null**，并在 note 里说明「缺什么、需补什么」，绝不编造数字。
- 输出：人类可读表 + JSON（顶层 metrics 数组，便于看板/CI 消费）。

依赖：psycopg2-binary（requirements.txt 已含），DSN 为同步 `postgresql://`。
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/

import sqlalchemy as sa  # noqa: E402

TZ = timezone(timedelta(hours=8))
DEFAULT_DSN = "postgresql://postgres:postgres@127.0.0.1:5432/ai_coach"
RETENTION_DAYS = 7


# ---------------------------------------------------------------------------
# 单一指标：能从库里真算的尽量真算，否则 value=None + 说明缺什么
# ---------------------------------------------------------------------------


def metric_retention_7d(conn, today) -> dict:
    """7 日留存：注册当日为 cohort，第 7 天有活跃（track_event）即视为留存。"""
    cutoff = today - timedelta(days=RETENTION_DAYS)
    track_total = conn.execute(sa.text("SELECT count(*) FROM track_event")).scalar_one()
    cohort, retained = conn.execute(
        sa.text(
            """
            SELECT count(*) AS cohort,
                   count(*) FILTER (WHERE EXISTS (
                       SELECT 1 FROM track_event t
                       WHERE t.user_id = u.id
                         AND (t.occurred_at AT TIME ZONE 'Asia/Shanghai')::date
                             = (u.created_at AT TIME ZONE 'Asia/Shanghai')::date + :days
                   )) AS retained
            FROM "user" u
            WHERE (u.created_at AT TIME ZONE 'Asia/Shanghai')::date <= :cutoff
            """
        ),
        {"days": RETENTION_DAYS, "cutoff": cutoff},
    ).one()
    ready = bool(track_total) and bool(cohort)
    value = round(retained / cohort, 4) if ready else None
    note = (
        f"cohort={cohort}（注册满 {RETENTION_DAYS} 天的用户），"
        f"第 {RETENTION_DAYS} 天回访={retained}"
        if ready
        else (
            "数据源缺失：track_event 无活跃事件（或暂无满窗 cohort），"
            "需前端上报活跃事件（login/日活）以判定留存"
        )
    )
    return _metric(
        "retention_7d",
        "新用户 7 日留存",
        value,
        "ratio",
        ">0.25",
        ready,
        "user.created_at + track_event.occurred_at/user_id",
        note,
    )


def metric_invite_k(conn) -> dict:
    """邀请 K 因子：成功邀请数 / 发起邀请的用户数（每个邀请人带来的新用户数）。"""
    inviters, accepted = conn.execute(
        sa.text(
            """
            SELECT count(DISTINCT inviter_id) AS inviters,
                   count(*) FILTER (WHERE invitee_id IS NOT NULL) AS accepted
            FROM invite
            WHERE inviter_id IS NOT NULL
            """
        )
    ).one()
    ready = bool(inviters)
    value = round(accepted / inviters, 4) if ready else None
    note = (
        f"邀请发起人={inviters}，成功邀请（invitee 已绑定）={accepted}"
        if ready
        else "数据源缺失：invite 表无邀请记录，需邀请裂变功能产生数据（inviter_id/invitee_id）"
    )
    return _metric(
        "invite_k",
        "邀请 K 因子",
        value,
        "ratio",
        ">0.5",
        ready,
        "invite.inviter_id/invitee_id",
        note,
    )


def metric_scan_conversion(conn) -> dict:
    """商家扫码转化率：上报 scan_in 的去重用户中，产生 order_pay 的比例。"""
    identity = "COALESCE(device_id, 'u:' || user_id::text)"
    scans, paid = conn.execute(
        sa.text(
            f"""
            SELECT
                count(DISTINCT {identity}) FILTER (WHERE event = 'scan_in')  AS scans,
                count(DISTINCT {identity}) FILTER (WHERE event = 'order_pay') AS paid
            FROM track_event
            """
        )
    ).one()
    ready = bool(scans)
    value = round(paid / scans, 4) if ready else None
    note = (
        f"扫码去重用户={scans}，其中下单去重用户={paid}"
        if ready
        else "数据源缺失：无 scan_in 埋点，需前端上报 scan_in/order_pay（带 device_id 匿名可识别）"
    )
    return _metric(
        "scan_conversion",
        "商家扫码转化率",
        value,
        "ratio",
        ">0.15",
        ready,
        "track_event(event=scan_in/order_pay, device_id)",
        note,
    )


def metric_recognize_success(conn) -> dict:
    """拍照识别成功率：track_event(event='ai_recognize') 中 success=true 的占比。

    数据源已就绪（前端 `ai_recognize` 上报 `properties.success/confidence/need_confirm`）；
    无数据时返回 null 并注明「待积累」，不编造。
    """
    row = conn.execute(
        sa.text(
            """
            SELECT count(*) AS total,
                   count(*) FILTER (WHERE properties->>'success' = 'true') AS success
            FROM track_event
            WHERE event = 'ai_recognize'
              AND properties->>'success' IN ('true', 'false')
            """
        )
    ).one()
    total = int(row.total or 0)
    success = int(row.success or 0)
    ready = total > 0
    value = round(success / total, 4) if ready else None
    note = (
        f"识别上报 {total} 次，成功 {success} 次"
        if ready
        else "数据源已就绪但暂无数据（待积累）：需前端上报 ai_recognize"
        "（properties.success/confidence/need_confirm）"
    )
    return _metric(
        "recognize_success",
        "拍照识别成功率",
        value,
        "ratio",
        ">0.85",
        ready,
        "track_event(event=ai_recognize, properties.success)",
        note,
    )


def metric_ai_satisfaction(conn) -> dict:
    """AI 问答满意度：track_event(event=ai_rating) 的 properties.score 均值（1~5）。"""
    row = conn.execute(
        sa.text(
            """
            SELECT avg((properties->>'score')::numeric) AS avg_score,
                   count(*) AS n
            FROM track_event
            WHERE event = 'ai_rating'
              AND properties ? 'score'
              AND properties->>'score' ~ '^[0-9]+(\\.[0-9]+)?$'
            """
        )
    ).one()
    n = int(row.n or 0)
    ready = n > 0
    value = round(float(row.avg_score), 2) if ready else None
    note = (
        f"收到评分 {n} 条，均值={value}"
        if ready
        else (
            "数据源缺失：无 ai_rating 埋点，"
            "需前端在 AI 回答后上报 ai_rating（properties.score 1~5）"
        )
    )
    return _metric(
        "ai_satisfaction",
        "AI 问答满意度",
        value,
        "score_1_5",
        ">4.5",
        ready,
        "track_event(event=ai_rating, properties.score)",
        note,
    )


def metric_cac(conn) -> dict:
    """内容获客成本（CAC）：需外部投放花费，库内无数据源，一律 null。"""
    return _metric(
        "cac",
        "内容获客成本",
        None,
        "cny_per_user",
        "<20",
        False,
        "（当前无数据源）",
        "数据源缺失（外部数据）：需导入投放花费（广告/内容投放账单）+ 同期新增用户数"
        "（user.created_at）；库内无花费表，不可由现有表推算",
    )


def _metric(key, name, value, unit, target, ready, source, note) -> dict:
    return {
        "key": key,
        "name": name,
        "value": value,
        "unit": unit,
        "target": target,
        "ready": ready,
        "source": source,
        "note": note,
    }


def build_report(conn, today) -> dict:
    metrics = [
        metric_retention_7d(conn, today),
        metric_invite_k(conn),
        metric_scan_conversion(conn),
        metric_recognize_success(conn),
        metric_ai_satisfaction(conn),
        metric_cac(conn),
    ]
    return {
        "generated_at": datetime.now(TZ).isoformat(),
        "dsn": None,  # 由 main 回填（不打印含口令的 DSN）
        "window": {
            "today": today.isoformat(),
            "retention_days": RETENTION_DAYS,
            "timezone": "Asia/Shanghai",
        },
        "metrics": metrics,
    }


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------


def _fmt(value, unit) -> str:
    if value is None:
        return "null"
    if unit == "ratio":
        return f"{value:.4f} ({value * 100:.2f}%)"
    if unit == "score_1_5":
        return f"{value:.2f}/5"
    if unit == "cny_per_user":
        return f"{value:.2f} 元/人"
    return str(value)


def print_table(report: dict) -> None:
    metrics = report["metrics"]
    head = ("指标", "数值", "目标", "就绪", "数据源")
    rows = [
        (
            m["name"],
            _fmt(m["value"], m["unit"]),
            m["target"],
            "是" if m["ready"] else "否",
            m["source"],
        )
        for m in metrics
    ]
    widths = [max(len(head[i]), *(len(r[i]) for r in rows)) for i in range(len(head))]

    def line(cols):
        return "  ".join(c.ljust(widths[i]) for i, c in enumerate(cols))

    print("=" * (sum(widths) + 2 * (len(widths) - 1)))
    print(f"F3 核心指标聚合报表  @ {report['generated_at']}  (TZ={report['window']['timezone']})")
    print(f"窗口 today={report['window']['today']}  留存窗={report['window']['retention_days']}d")
    print("=" * (sum(widths) + 2 * (len(widths) - 1)))
    print(line(head))
    print(line(["-" * w for w in widths]))
    for r in rows:
        print(line(r))
    print()
    print("未就绪指标说明（数据源缺失 + 需补什么）：")
    for m in metrics:
        if not m["ready"]:
            print(f"  - {m['name']}: {m['note']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="F3 核心指标聚合报表（6 项）")
    parser.add_argument("--dsn", default=DEFAULT_DSN, help="同步 PostgreSQL DSN")
    args = parser.parse_args()

    engine = sa.create_engine(args.dsn)
    today = datetime.now(TZ).date()
    try:
        with engine.connect() as conn:
            report = build_report(conn, today)
    except sa.exc.SQLAlchemyError as exc:
        print(f"[ERROR] 连接/查询失败: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    print_table(report)
    print("\n---- JSON ----")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
