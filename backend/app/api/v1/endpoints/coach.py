"""真人教练工单域接口（openapi: /api/coach/*）。

**G1 缺口：真人健身教练工单（教练端查看分配用户/回复工单）、专家问诊。**
本文件只做**协议层**：鉴权依赖 + 参数校验 + schema 组装，业务逻辑全在
`app/services/coach_service.py`（提问扣次/自动分配/状态流转/行级隔离/限流）。

- 8 个接口路径/方法与 `contracts/openapi.yaml` 逐一对齐（契约一致性测试门禁）；
- 行级隔离硬约束：教练端所有查询强制带 `coach_id = 当前教练`，越权/未分配 → 3001。

教练身份【假设，已采纳】：复用 `admin_user`（role=4 教练）+ admin 域 JWT，
`get_current_coach` 镜像 `admin.py::get_current_admin` 的解析方式；额外按 username 关联
`coach` 名册表，取 `coach.id` 作为 coach_id（工单外键）。文档明言首期不做 RBAC，取最简可行。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_request_id
from app.core.errors import AppException
from app.core.security import decode_token
from app.db.session import get_db
from app.models import AdminUser, Coach
from app.schemas import Envelope
from app.schemas.auth import UserBrief
from app.schemas.coach import (
    CoachAssignedTicketListData,
    CoachAssignedUserItem,
    CoachAssignedUserPageData,
    CoachLoginData,
    CoachLoginIn,
    CoachMessageData,
    CoachMessageIn,
    CoachReplyData,
    CoachTicketCreatedData,
    CoachTicketDetailData,
    CoachTicketIn,
    CoachTicketItem,
    CoachTicketMessageItem,
    CoachTicketPageData,
    CoachUserProfile,
    CoachUserRecordItem,
)
from app.schemas.common import ErrorCode, PageMeta, ok
from app.services import coach_service
from app.services.coach_service import CoachPrincipal

router = APIRouter(tags=["教练工单"])

_coach_bearer = HTTPBearer(auto_error=False, scheme_name="bearerAuth")


# 认证依赖


async def get_current_coach(
    credentials: HTTPAuthorizationCredentials | None = Depends(_coach_bearer),
    session: AsyncSession = Depends(get_db),
) -> CoachPrincipal:
    """Bearer JWT（admin 域）→ CoachPrincipal；非教练角色/无名册 → 1002，无效 → 1001。"""
    if credentials is None or not credentials.credentials:
        raise AppException(ErrorCode.UNAUTHORIZED)
    payload = decode_token(credentials.credentials, expected_type="access", expected_dom="admin")
    try:
        admin_id = int(payload.get("sub", ""))
    except (TypeError, ValueError) as exc:
        raise AppException(ErrorCode.UNAUTHORIZED) from exc
    admin = (
        await session.execute(select(AdminUser).where(AdminUser.id == admin_id))
    ).scalar_one_or_none()
    if admin is None:
        raise AppException(ErrorCode.UNAUTHORIZED)
    if admin.role != coach_service.ROLE_COACH:  # 首期不做 RBAC：非教练账号一律拒绝
        raise AppException(ErrorCode.FORBIDDEN)
    coach = (
        await session.execute(select(Coach).where(Coach.username == admin.username))
    ).scalar_one_or_none()
    if coach is None or coach.status != 1:  # 名册缺失/停用 → 无权限
        raise AppException(ErrorCode.FORBIDDEN)
    return CoachPrincipal(
        id=coach.id, admin_id=admin.id, username=admin.username, role=admin.role, name=coach.name
    )


# 教练登录（security: []，无需认证）


@router.post(
    "/coach/login", response_model=Envelope[CoachLoginData], summary="教练登录（账号密码）"
)
async def coach_login(
    payload: CoachLoginIn,
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[CoachLoginData]:
    access_token, refresh_token = await coach_service.login(
        session, payload.username, payload.password
    )
    return ok(
        CoachLoginData(access_token=access_token, refresh_token=refresh_token),
        request_id=request_id,
    )


# 用户侧：提问 / 我的工单 / 工单详情 / 追加描述


@router.post(
    "/coach/ticket", response_model=Envelope[CoachTicketCreatedData], summary="提问/问诊下单"
)
async def create_coach_ticket(
    payload: CoachTicketIn,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[CoachTicketCreatedData]:
    ticket = await coach_service.create_ticket(session, user.id, payload.question)
    return ok(
        CoachTicketCreatedData(
            ticket_id=ticket.id, status=ticket.status, created_at=ticket.created_at
        ),
        request_id=request_id,
    )


@router.get("/coach/tickets", response_model=Envelope[CoachTicketPageData], summary="我的工单列表")
async def list_my_coach_tickets(
    status: int | None = Query(default=None, ge=1, le=3),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[CoachTicketPageData]:
    rows, total = await coach_service.list_my_tickets(session, user.id, status, page, page_size)
    return ok(
        CoachTicketPageData(
            items=[CoachTicketItem.model_validate(r) for r in rows],
            page=PageMeta(page=page, page_size=page_size, total=total),
        ),
        request_id=request_id,
    )


@router.get(
    "/coach/ticket/{id}",
    response_model=Envelope[CoachTicketDetailData],
    summary="工单详情（含消息）",
)
async def get_coach_ticket(
    id: int,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[CoachTicketDetailData]:
    ticket, messages = await coach_service.get_ticket_detail(session, user.id, id)
    return ok(
        CoachTicketDetailData(
            ticket=CoachTicketItem.model_validate(ticket),
            messages=[CoachTicketMessageItem.model_validate(m) for m in messages],
        ),
        request_id=request_id,
    )


@router.post(
    "/coach/ticket/{id}/message", response_model=Envelope[CoachMessageData], summary="用户追加描述"
)
async def add_coach_ticket_message(
    id: int,
    payload: CoachMessageIn,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[CoachMessageData]:
    msg = await coach_service.add_user_message(session, user.id, id, payload.content)
    return ok(CoachMessageData(message_id=msg.id), request_id=request_id)


# 教练侧：被分配用户 / 被分配工单 / 回复


@router.get(
    "/coach/assigned-users",
    response_model=Envelope[CoachAssignedUserPageData],
    summary="教练查看被分配用户档案 + 近期记录",
)
async def list_assigned_users(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    coach: CoachPrincipal = Depends(get_current_coach),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[CoachAssignedUserPageData]:
    items, total = await coach_service.list_assigned_users(session, coach.id, page, page_size)
    return ok(
        CoachAssignedUserPageData(
            items=[
                CoachAssignedUserItem(
                    user=UserBrief(
                        id=uid,
                        nickname=u.nickname if u else "",
                        avatar_url=u.avatar_url if u else None,
                    ),
                    profile=(
                        CoachUserProfile(
                            gender=p.gender,
                            height_cm=p.height_cm,
                            current_weight=p.current_weight,
                            target_weight=p.target_weight,
                            target_calories=p.target_calories,
                        )
                        if p
                        else None
                    ),
                    recent_records=[
                        CoachUserRecordItem(
                            date=s.snapshot_date,
                            intake=s.intake,
                            deficit=s.deficit,
                            steps=s.steps,
                        )
                        for s in records
                    ],
                )
                for uid, u, p, records in items
            ],
            page=PageMeta(page=page, page_size=page_size, total=total),
        ),
        request_id=request_id,
    )


@router.get(
    "/coach/assigned-tickets",
    response_model=Envelope[CoachAssignedTicketListData],
    summary="教练域工单列表（仅本人被分配）",
)
async def list_assigned_tickets(
    status: int | None = Query(default=None, ge=1, le=3),
    coach: CoachPrincipal = Depends(get_current_coach),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[CoachAssignedTicketListData]:
    rows = await coach_service.list_assigned_tickets(session, coach.id, status)
    return ok(
        CoachAssignedTicketListData(items=[CoachTicketItem.model_validate(r) for r in rows]),
        request_id=request_id,
    )


@router.post(
    "/coach/ticket/{id}/reply", response_model=Envelope[CoachReplyData], summary="教练回复工单"
)
async def reply_coach_ticket(
    id: int,
    payload: CoachMessageIn,
    coach: CoachPrincipal = Depends(get_current_coach),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[CoachReplyData]:
    msg, status = await coach_service.reply_ticket(session, coach.id, id, payload.content)
    return ok(CoachReplyData(message_id=msg.id, status=status), request_id=request_id)
