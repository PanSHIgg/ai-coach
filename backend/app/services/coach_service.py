"""真人教练工单域业务（openapi: /api/coach/*）。

端到端闭环：用户提问（扣 `user_benefit.coach_times_left`）→ 自动分配教练 → 教练回复
（status 1→2）→ 用户追问（status →1）→ 关闭（3）。

硬约束（本域最重要的不变量）：
- **行级隔离**：教练侧所有读写都带 `coach_id = 当前教练`，未分配给他人的工单/用户
  一律 3001（不区分「不存在」与「非本人」，避免资源探测）；
- **次数扣减并发安全**：`user_benefit` 行 `FOR UPDATE` 加锁读，扣减与落单在同一事务
  末尾一次 commit（与 `ai_service.ensure_benefit` 同口径），避免并发超用名额。

【假设】教练身份复用 `admin_user`(role=4) + `coach` 名册（username 唯一关联），
首期不做 RBAC；工单分配取「在职教练中在手未结工单最少者」，无在职教练时留空
（coach_id=NULL，教练端不可见，不阻塞用户提问）。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppException
from app.core.rate_limit import check_rate_limit
from app.core.security import (
    create_access_token,
    create_refresh_token,
    verify_password,
)
from app.models import (
    AdminUser,
    BodyProfile,
    Coach,
    CoachTicket,
    CoachTicketMessage,
    DailySnapshot,
    User,
    UserBenefit,
)
from app.schemas.common import ErrorCode

ROLE_COACH = 4  # admin_user.role：教练【假设】
TICKET_STATUS_PENDING = 1  # 1待回复
TICKET_STATUS_REPLIED = 2  # 2已回复
TICKET_STATUS_CLOSED = 3  # 3已关闭
SENDER_USER = 1  # coach_ticket_message.sender_role
SENDER_COACH = 2

TITLE_MAX = 64  # coach_ticket.title 列宽；title 取 question 前缀
RECENT_RECORD_DAYS = 7  # 教练侧「近 7 日记录」回看窗口（含今日）
ASSIGNED_TICKET_MAX = 100  # 教练域工单单次返回上限（契约未分页，防全表）
TICKET_PER_MIN = 20  # 提问限流：20 次/分钟/用户（契约 429）


class CoachPrincipal(BaseModel):
    """解析出的教练身份（镜像 admin_service.AdminPrincipal）。"""

    id: int  # coach.id —— 工单 coach_id 外键与行级隔离键
    admin_id: int  # admin_user.id —— JWT subject
    username: str
    role: int
    name: Optional[str] = None


def _now() -> datetime:
    return datetime.now(UTC)


# 教练登录


async def login(session: AsyncSession, username: str, password: str) -> tuple[str, str]:
    """教练登录：admin_user(role=4) + coach 名册双校验 → (access_token, refresh_token)。

    账号不存在 / 非教练 / 名册缺失或停用 / 口令错误统一 1001（不泄漏账号是否存在）；
    【假设】名册缺失的教练账号同样拒绝登录，否则签发后每个教练端接口都会 1002。
    """
    admin = (
        await session.execute(select(AdminUser).where(AdminUser.username == username))
    ).scalar_one_or_none()
    if admin is None or admin.role != ROLE_COACH:
        raise AppException(ErrorCode.UNAUTHORIZED)
    if not verify_password(password, admin.password_hash):
        raise AppException(ErrorCode.UNAUTHORIZED)
    coach = (
        await session.execute(select(Coach).where(Coach.username == username))
    ).scalar_one_or_none()
    if coach is None or coach.status != 1:
        raise AppException(ErrorCode.UNAUTHORIZED)
    return (
        create_access_token(str(admin.id), dom="admin", role=admin.role),
        create_refresh_token(str(admin.id), dom="admin", role=admin.role),
    )


# 用户侧：提问 / 我的工单 / 详情 / 追加描述


async def _pick_coach(session: AsyncSession) -> int | None:
    """自动分配：在职教练中「在手未结工单（status 1/2）最少」者，同数取 id 小者。

    【假设】无专家分类维度（表结构无该列），一律按「最少负载」轮转；无在职教练时返回 None。
    """
    return (
        await session.execute(
            select(Coach.id)
            .outerjoin(
                CoachTicket,
                (CoachTicket.coach_id == Coach.id)
                & CoachTicket.status.in_((TICKET_STATUS_PENDING, TICKET_STATUS_REPLIED)),
            )
            .where(Coach.status == 1)
            .group_by(Coach.id)
            .order_by(func.count(CoachTicket.id).asc(), Coach.id.asc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def create_ticket(session: AsyncSession, user_id: int, question: str) -> CoachTicket:
    """提问/专家问诊：限流 → 扣次数（为 0 → 4001）→ 落工单(status=1) + 首条用户消息。

    `user_benefit` 行锁内完成「读余额 → 扣减 → 落单」，末尾一次 commit，防并发超用。
    """
    if not await check_rate_limit(f"coach:ticket:user:{user_id}", TICKET_PER_MIN):
        raise AppException(ErrorCode.RATE_LIMITED)
    benefit = (
        await session.execute(
            select(UserBenefit).where(UserBenefit.user_id == user_id).with_for_update()
        )
    ).scalar_one_or_none()
    if benefit is None or int(benefit.coach_times_left or 0) <= 0:
        raise AppException(ErrorCode.QUOTA_EXCEEDED, "真人教练次数不足")
    benefit.coach_times_left = int(benefit.coach_times_left) - 1

    ticket = CoachTicket(
        user_id=user_id,
        coach_id=await _pick_coach(session),
        title=question[:TITLE_MAX],
        status=TICKET_STATUS_PENDING,
    )
    session.add(ticket)
    await session.flush()
    session.add(
        CoachTicketMessage(
            ticket_id=ticket.id,
            sender_role=SENDER_USER,
            user_id=user_id,
            content=question,
        )
    )
    await session.commit()
    await session.refresh(ticket)
    return ticket


async def list_my_tickets(
    session: AsyncSession,
    user_id: int,
    status: int | None,
    page: int,
    page_size: int,
) -> tuple[list[CoachTicket], int]:
    """我的工单（仅本人，created_at DESC）。"""
    conds = [CoachTicket.user_id == user_id]
    if status is not None:
        conds.append(CoachTicket.status == status)
    total = int(
        (
            await session.execute(
                select(func.count()).select_from(CoachTicket).where(*conds)
            )
        ).scalar_one()
    )
    rows = (
        (
            await session.execute(
                select(CoachTicket)
                .where(*conds)
                .order_by(CoachTicket.created_at.desc(), CoachTicket.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return list(rows), total


async def get_ticket_detail(
    session: AsyncSession, user_id: int, ticket_id: int
) -> tuple[CoachTicket, list[CoachTicketMessage]]:
    """工单详情（含对话流水）；非本人工单 → 3001。"""
    ticket = await session.get(CoachTicket, ticket_id)
    if ticket is None or ticket.user_id != user_id:
        raise AppException(ErrorCode.NOT_FOUND)
    rows = (
        (
            await session.execute(
                select(CoachTicketMessage)
                .where(CoachTicketMessage.ticket_id == ticket_id)
                .order_by(CoachTicketMessage.created_at.asc(), CoachTicketMessage.id.asc())
            )
        )
        .scalars()
        .all()
    )
    return ticket, list(rows)


async def add_user_message(
    session: AsyncSession, user_id: int, ticket_id: int, content: str
) -> CoachTicketMessage:
    """用户追加描述/追问：非本人 → 3001；已关闭工单不可追加 → 2001；否则工单回到 1 待回复。"""
    ticket = (
        await session.execute(
            select(CoachTicket).where(CoachTicket.id == ticket_id).with_for_update()
        )
    ).scalar_one_or_none()
    if ticket is None or ticket.user_id != user_id:
        raise AppException(ErrorCode.NOT_FOUND)
    if ticket.status == TICKET_STATUS_CLOSED:  # 【假设】已关闭工单不再接受追问
        raise AppException(ErrorCode.VALIDATION_ERROR, "工单已关闭，不可追加描述")
    msg = CoachTicketMessage(
        ticket_id=ticket_id,
        sender_role=SENDER_USER,
        user_id=user_id,
        content=content,
    )
    session.add(msg)
    ticket.status = TICKET_STATUS_PENDING
    ticket.updated_at = _now()
    await session.commit()
    await session.refresh(msg)
    return msg


# 教练侧：被分配用户 / 被分配工单 / 回复


async def list_assigned_users(
    session: AsyncSession, coach_id: int, page: int, page_size: int
) -> tuple[list, int]:
    """被分配给该教练的用户（工单去重）+ 档案 + 近 7 日 `daily_snapshot` 摘要。

    返回 `(items, total)`，item 为 `(user_id, user, profile, records)` 四元组，由路由层组装
    schema（service 不依赖 schema 出参，保持与既有 service 一致）。
    """
    owned = CoachTicket.coach_id == coach_id
    total = int(
        (
            await session.execute(
                select(func.count(func.distinct(CoachTicket.user_id))).where(owned)
            )
        ).scalar_one()
    )
    user_ids = list(
        (
            await session.execute(
                select(CoachTicket.user_id)
                .where(owned)
                .group_by(CoachTicket.user_id)
                .order_by(CoachTicket.user_id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    if not user_ids:
        return [], total

    users = {
        u.id: u
        for u in (
            await session.execute(select(User).where(User.id.in_(user_ids)))
        ).scalars()
    }
    profiles = {
        p.user_id: p
        for p in (
            await session.execute(select(BodyProfile).where(BodyProfile.user_id.in_(user_ids)))
        ).scalars()
    }
    since = _now().date() - timedelta(days=RECENT_RECORD_DAYS - 1)  # 含今日共 7 个自然日
    rows = (
        (
            await session.execute(
                select(DailySnapshot)
                .where(
                    DailySnapshot.user_id.in_(user_ids),
                    DailySnapshot.snapshot_date >= since,
                )
                .order_by(DailySnapshot.snapshot_date.desc())
            )
        )
        .scalars()
        .all()
    )
    records: dict[int, list[DailySnapshot]] = {uid: [] for uid in user_ids}
    for row in rows:
        bucket = records.get(row.user_id)
        if bucket is None or len(bucket) >= RECENT_RECORD_DAYS:
            continue
        bucket.append(row)

    items = [
        (uid, users.get(uid), profiles.get(uid), records.get(uid, [])) for uid in user_ids
    ]
    return items, total


async def list_assigned_tickets(
    session: AsyncSession, coach_id: int, status: int | None
) -> list[CoachTicket]:
    """教练域工单列表（行级隔离：仅本人被分配，created_at DESC，上限 100 条）。"""
    conds = [CoachTicket.coach_id == coach_id]
    if status is not None:
        conds.append(CoachTicket.status == status)
    rows = (
        (
            await session.execute(
                select(CoachTicket)
                .where(*conds)
                .order_by(CoachTicket.created_at.desc(), CoachTicket.id.desc())
                .limit(ASSIGNED_TICKET_MAX)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def reply_ticket(
    session: AsyncSession, coach_id: int, ticket_id: int, content: str
) -> tuple[CoachTicketMessage, int]:
    """教练回复：未分配给本人的工单 → 3001；回复后 status=2 已回复。"""
    ticket = (
        await session.execute(
            select(CoachTicket).where(CoachTicket.id == ticket_id).with_for_update()
        )
    ).scalar_one_or_none()
    # 行级隔离：不区分「不存在」与「非本人」，防资源探测
    if ticket is None or ticket.coach_id != coach_id:
        raise AppException(ErrorCode.NOT_FOUND)
    msg = CoachTicketMessage(
        ticket_id=ticket_id,
        sender_role=SENDER_COACH,
        coach_id=coach_id,
        content=content,
    )
    session.add(msg)
    ticket.status = TICKET_STATUS_REPLIED
    ticket.updated_at = _now()
    await session.commit()
    await session.refresh(msg)
    return msg, ticket.status
