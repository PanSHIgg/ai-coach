"""任务中心 / 每日签到 / 积分服务（openapi: /api/task/*、/api/points、/api/points/list）。

口径（docs/split/03-页面布局与交互说明.md §5.5 我的页）：
- 任务中心三类：每日签到 +5 积分 / 完善档案送轻食券 / 首次 AI 检测送运动券；
- 积分门槛：500→免费轻食券 / 800→免费运动券 / 1500→50 元抵扣券。

状态推算基于**真实状态**（body_profile 是否已建、是否存在 ai_dialog、当日是否已签到），
`user_task` 行惰性初始化（INSERT ... ON CONFLICT DO UPDATE），已领奖（status=2）不降级。
签到以 `daily_checkin(user_id, checkin_date)` 唯一约束保证当日幂等。

日期口径 UTC+8，与 `app/services/account.py` / `ai_service.py` 一致。
"""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AiDialog, BodyProfile, DailyCheckin, PointsLog, UserPoints, UserTask
from app.schemas.common import PageMeta
from app.schemas.task import (
    PointsOverviewData,
    PointsPageData,
    PointsRecordItem,
    PointsThreshold,
    TaskCheckinData,
    TaskItem,
    TaskListData,
)

TZ = timezone(timedelta(hours=8))

DAILY_CHECKIN_POINTS = 5
CHECKIN_REASON = "每日签到"

# 任务定义：(code, name, reward_points, reward_desc)
# 【假设】reward_points 仅签到有积分奖励；另两类奖励为券，分值 0、文案承载券种。
TASK_DEFS: tuple[tuple[str, str, int, str], ...] = (
    ("daily_checkin", "每日签到", DAILY_CHECKIN_POINTS, "+5积分"),
    ("complete_profile", "完善档案", 0, "送轻食券"),
    ("first_ai_check", "首次AI检测", 0, "送运动券"),
)

# 积分兑换门槛（docs §5.5-6）
POINTS_THRESHOLDS: tuple[tuple[int, str], ...] = (
    (500, "免费轻食券"),
    (800, "免费运动券"),
    (1500, "50元抵扣券"),
)


async def _exists(session: AsyncSession, stmt) -> bool:
    """存在性判断（LIMIT 1）。"""
    return await session.scalar(stmt) is not None


async def _real_completion(session: AsyncSession, *, user_id: int, today: date) -> dict[str, bool]:
    """按真实状态推算各任务完成情况。"""
    has_profile = await _exists(
        session, select(BodyProfile.id).where(BodyProfile.user_id == user_id).limit(1)
    )
    has_dialog = await _exists(
        session, select(AiDialog.id).where(AiDialog.user_id == user_id).limit(1)
    )
    checked_in = await _exists(
        session,
        select(DailyCheckin.id)
        .where(DailyCheckin.user_id == user_id, DailyCheckin.checkin_date == today)
        .limit(1),
    )
    return {
        "daily_checkin": checked_in,
        "complete_profile": has_profile,
        "first_ai_check": has_dialog,
    }


async def _sync_user_tasks(
    session: AsyncSession, *, user_id: int, completion: dict[str, bool]
) -> None:
    """惰性初始化/同步 user_task 行（不降级已领奖 status=2）。"""
    now = datetime.now(TZ)
    for code, _name, reward, _desc in TASK_DEFS:
        done = completion.get(code, False)
        status = 1 if done else 0
        values = {
            "user_id": user_id,
            "task_code": code,
            "status": status,
            "progress": 100 if done else 0,
            "reward_points": reward,
            "completed_at": now if done else None,
        }
        stmt = pg_insert(UserTask).values(**values)
        set_ = {
            "status": func.greatest(UserTask.status, status),
            # 与 status 同口径取最大：避免「已领奖但 progress 被重置为 0」的落库自相矛盾
            "progress": func.greatest(UserTask.progress, values["progress"]),
            "reward_points": reward,
        }
        if done:
            set_["completed_at"] = func.coalesce(UserTask.completed_at, func.now())
        stmt = stmt.on_conflict_do_update(index_elements=["user_id", "task_code"], set_=set_)
        await session.execute(stmt)
    await session.commit()


async def list_tasks(session: AsyncSession, *, user_id: int) -> TaskListData:
    """返回任务中心列表（含每日签到状态）。"""
    today = datetime.now(TZ).date()
    completion = await _real_completion(session, user_id=user_id, today=today)
    await _sync_user_tasks(session, user_id=user_id, completion=completion)

    items = [
        TaskItem(
            code=code,
            name=name,
            reward_points=reward,
            reward_desc=desc,
            status=1 if completion.get(code, False) else 0,
            progress=100 if completion.get(code, False) else 0,
        )
        for code, name, reward, desc in TASK_DEFS
    ]
    return TaskListData(items=items)


async def _streak(session: AsyncSession, *, user_id: int, today: date) -> int:
    """连续签到天数（含今天，向前逐日计数至断档）。"""
    dates = (
        await session.scalars(
            select(DailyCheckin.checkin_date)
            .where(
                DailyCheckin.user_id == user_id,
                DailyCheckin.checkin_date <= today,
            )
            .order_by(DailyCheckin.checkin_date.desc())
        )
    ).all()
    streak = 0
    expected = today
    for d in dates:
        if d == expected:
            streak += 1
            expected -= timedelta(days=1)
        else:
            break
    return streak


async def checkin(session: AsyncSession, *, user_id: int) -> TaskCheckinData:
    """每日签到（同一用户当日幂等；重复签到 points_added=0、streak 不变）。"""
    today = datetime.now(TZ).date()
    inserted_id = await session.scalar(
        pg_insert(DailyCheckin)
        .values(user_id=user_id, checkin_date=today, points=DAILY_CHECKIN_POINTS)
        .on_conflict_do_nothing(index_elements=["user_id", "checkin_date"])
        .returning(DailyCheckin.id)
    )
    added = 0
    if inserted_id is not None:
        added = DAILY_CHECKIN_POINTS
        await session.execute(
            pg_insert(UserPoints)
            .values(user_id=user_id, balance=0, total_earned=0)
            .on_conflict_do_nothing(index_elements=["user_id"])
        )
        await session.execute(
            update(UserPoints)
            .where(UserPoints.user_id == user_id)
            .values(
                balance=UserPoints.balance + DAILY_CHECKIN_POINTS,
                total_earned=UserPoints.total_earned + DAILY_CHECKIN_POINTS,
            )
        )
        session.add(
            PointsLog(
                user_id=user_id,
                change=DAILY_CHECKIN_POINTS,
                reason=CHECKIN_REASON,
                ref=f"checkin:{today.isoformat()}",
            )
        )
        await session.commit()

    balance = await session.scalar(
        select(UserPoints.balance).where(UserPoints.user_id == user_id)
    )
    return TaskCheckinData(
        points_added=added,
        total_points=int(balance or 0),
        streak=await _streak(session, user_id=user_id, today=today),
    )


async def get_points_overview(session: AsyncSession, *, user_id: int) -> PointsOverviewData:
    """返回积分概览（余额/累计获得/兑换门槛）。"""
    await session.execute(
        pg_insert(UserPoints)
        .values(user_id=user_id, balance=0, total_earned=0)
        .on_conflict_do_nothing(index_elements=["user_id"])
    )
    await session.commit()
    row = (
        await session.execute(select(UserPoints).where(UserPoints.user_id == user_id))
    ).scalar_one()
    return PointsOverviewData(
        balance=int(row.balance),
        total_earned=int(row.total_earned),
        thresholds=[PointsThreshold(points=p, reward_desc=d) for p, d in POINTS_THRESHOLDS],
    )


async def list_points(
    session: AsyncSession,
    *,
    user_id: int,
    type: int | None,
    page: int,
    page_size: int,
) -> PointsPageData:
    """返回积分明细分页（type 1获得 2消耗；缺省=全部）。"""
    conds = [PointsLog.user_id == user_id]
    if type == 1:
        conds.append(PointsLog.change > 0)
    elif type == 2:
        conds.append(PointsLog.change < 0)

    total = await session.scalar(select(func.count()).select_from(PointsLog).where(*conds))
    rows = (
        await session.scalars(
            select(PointsLog)
            .where(*conds)
            .order_by(PointsLog.created_at.desc(), PointsLog.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    items = [
        PointsRecordItem(change=int(r.change), reason=r.reason, created_at=r.created_at)
        for r in rows
    ]
    return PointsPageData(
        items=items, page=PageMeta(page=page, page_size=page_size, total=int(total or 0))
    )