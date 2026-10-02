"""任务中心 / 每日签到 / 积分测试（G3）。

覆盖：签到幂等（唯一约束保证当日一次）、积分累加与流水、连续签到天数、
任务状态按真实状态推算（body_profile / ai_dialog / 当日签到）、积分概览门槛与明细分页过滤。
真实 PostgreSQL，沿用 conftest 的 db_client / db_session / authed。
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.models import AiDialog, BodyProfile, DailyCheckin, PointsLog, UserPoints, UserTask

TZ = timezone(timedelta(hours=8))


def _today():
    return datetime.now(TZ).date()


async def test_checkin_is_idempotent_per_day(db_client, db_session, authed):
    first = (await db_client.post("/api/task/checkin", headers=authed["headers"])).json()["data"]
    assert first == {"points_added": 5, "total_points": 5, "streak": 1}

    again = (await db_client.post("/api/task/checkin", headers=authed["headers"])).json()["data"]
    assert again == {"points_added": 0, "total_points": 5, "streak": 1}

    uid = authed["user_id"]
    balance = await db_session.scalar(select(UserPoints.balance).where(UserPoints.user_id == uid))
    earned = await db_session.scalar(
        select(UserPoints.total_earned).where(UserPoints.user_id == uid)
    )
    assert (balance, earned) == (5, 5)
    logs = (
        await db_session.scalars(select(PointsLog).where(PointsLog.user_id == uid))
    ).all()
    assert len(logs) == 1 and logs[0].change == 5
    count = await db_session.scalar(
        select(func.count()).select_from(DailyCheckin).where(DailyCheckin.user_id == uid)
    )
    assert count == 1


@pytest.mark.parametrize("offsets,expected", [((1, 2), 3), ((1, 3), 2)])
async def test_checkin_streak_counts_consecutive_days(db_client, db_session, authed, offsets, expected):
    """已签到历史 + 今日签到 → 从今天向前连续计数，遇断档停止。"""
    today = _today()
    db_session.add_all(
        [
            DailyCheckin(user_id=authed["user_id"], checkin_date=today - timedelta(days=o), points=5)
            for o in offsets
        ]
    )
    await db_session.commit()
    data = (await db_client.post("/api/task/checkin", headers=authed["headers"])).json()["data"]
    assert data["streak"] == expected


async def test_task_list_reflects_real_state(db_client, db_session, authed):
    uid = authed["user_id"]
    items = (await db_client.get("/api/task/list", headers=authed["headers"])).json()["data"]["items"]
    assert [it["code"] for it in items] == [
        "daily_checkin",
        "complete_profile",
        "first_ai_check",
    ]
    assert all(it["status"] == 0 and it["progress"] == 0 for it in items)
    # 惰性初始化 user_task 三行
    rows = await db_session.scalar(
        select(func.count()).select_from(UserTask).where(UserTask.user_id == uid)
    )
    assert rows == 3

    db_session.add(
        BodyProfile(
            user_id=uid,
            gender=1,
            height_cm=175,
            age=30,
            current_weight=70.0,
            target_type=1,
            activity_level=2,
            goal_pace=1,
        )
    )
    db_session.add(AiDialog(user_id=uid, role="user", content="你好"))
    await db_session.commit()

    items = (await db_client.get("/api/task/list", headers=authed["headers"])).json()["data"]["items"]
    by_code = {it["code"]: it for it in items}
    assert by_code["complete_profile"]["status"] == 1
    assert by_code["complete_profile"]["progress"] == 100
    assert by_code["first_ai_check"]["status"] == 1
    assert by_code["daily_checkin"]["status"] == 0
    # 奖励元数据与文档一致
    assert by_code["daily_checkin"]["reward_points"] == 5
    assert by_code["complete_profile"]["reward_desc"] == "送轻食券"
    assert by_code["first_ai_check"]["reward_desc"] == "送运动券"

    await db_client.post("/api/task/checkin", headers=authed["headers"])
    items = (await db_client.get("/api/task/list", headers=authed["headers"])).json()["data"]["items"]
    by_code = {it["code"]: it for it in items}
    assert by_code["daily_checkin"]["status"] == 1


async def test_points_overview_thresholds_and_lazy_init(db_client, authed):
    data = (await db_client.get("/api/points", headers=authed["headers"])).json()["data"]
    assert data["balance"] == 0 and data["total_earned"] == 0
    assert data["thresholds"] == [
        {"points": 500, "reward_desc": "免费轻食券"},
        {"points": 800, "reward_desc": "免费运动券"},
        {"points": 1500, "reward_desc": "50元抵扣券"},
    ]


async def test_points_list_pagination_and_type_filter(db_client, db_session, authed):
    uid = authed["user_id"]
    db_session.add_all(
        [
            PointsLog(user_id=uid, change=5, reason="每日签到"),
            PointsLog(user_id=uid, change=100, reason="邀请奖励"),
            PointsLog(user_id=uid, change=-50, reason="兑换轻食券"),
        ]
    )
    await db_session.commit()

    page = (
        await db_client.get("/api/points/list?page=1&page_size=2", headers=authed["headers"])
    ).json()["data"]
    assert page["page"]["total"] == 3
    assert len(page["items"]) == 2

    gained = (await db_client.get("/api/points/list?type=1", headers=authed["headers"])).json()[
        "data"
    ]
    assert gained["page"]["total"] == 2
    assert all(it["change"] > 0 for it in gained["items"])

    spent = (await db_client.get("/api/points/list?type=2", headers=authed["headers"])).json()[
        "data"
    ]
    assert spent["page"]["total"] == 1
    assert spent["items"][0]["change"] == -50
    assert spent["items"][0]["reason"] == "兑换轻食券"
    assert spent["items"][0]["created_at"]