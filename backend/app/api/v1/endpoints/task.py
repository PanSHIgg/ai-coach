"""任务中心 / 每日签到 / 积分接口（openapi: /api/task/*、/api/points、/api/points/list）。

本文件为**协议层骨架**（Wave A 地基）：参数校验 + schema 组装 + 调用 service；
业务逻辑在 `app/services/task_service.py`（Wave B feature 代理填充实现）。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_current_user, get_request_id
from app.db.session import get_db
from app.schemas import Envelope
from app.schemas.common import ok
from app.schemas.task import (
    PointsOverviewData,
    PointsPageData,
    TaskCheckinData,
    TaskListData,
)
from app.services import task_service

router = APIRouter(tags=["任务与积分"])


@router.get("/task/list", response_model=Envelope[TaskListData], summary="任务中心列表")
async def task_list(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[TaskListData]:
    data = await task_service.list_tasks(session, user_id=int(user.id))
    return ok(data, request_id=request_id)


@router.post(
    "/task/checkin",
    response_model=Envelope[TaskCheckinData],
    summary="每日签到（同一用户当日幂等）",
)
async def task_checkin(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[TaskCheckinData]:
    data = await task_service.checkin(session, user_id=int(user.id))
    return ok(data, request_id=request_id)


@router.get("/points", response_model=Envelope[PointsOverviewData], summary="积分概览")
async def get_points(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[PointsOverviewData]:
    data = await task_service.get_points_overview(session, user_id=int(user.id))
    return ok(data, request_id=request_id)


@router.get("/points/list", response_model=Envelope[PointsPageData], summary="积分明细（分页）")
async def list_points(
    type_: int | None = Query(default=None, alias="type", ge=1, le=2),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[PointsPageData]:
    data = await task_service.list_points(
        session, user_id=int(user.id), type=type_, page=page, page_size=page_size
    )
    return ok(data, request_id=request_id)