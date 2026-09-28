"""体重记录接口（openapi: /api/weight*，BE-w 归属本模块）。

GET /api/weight/list、POST /api/weight、DELETE /api/weight/{id}、GET /api/weight/trend。
行级隔离 user_id；写操作走事务。
"""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_current_user, get_request_id
from app.db.session import get_db
from app.schemas import Envelope
from app.schemas.common import ok
from app.schemas.weight import (
    WeightDeleteData,
    WeightPageData,
    WeightRecordIn,
    WeightRecordOut,
    WeightTrendData,
)
from app.services import weight_service

router = APIRouter(tags=["体重"])


@router.get("/weight/list", response_model=Envelope[WeightPageData], summary="体重记录列表")
async def list_weights(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
    session: AsyncSession = Depends(get_db),
) -> Envelope[WeightPageData]:
    data = await weight_service.list_weights(session, user.id, page, page_size)
    return ok(data, request_id=request_id)


@router.post("/weight", response_model=Envelope[WeightRecordOut], summary="新增体重记录")
async def create_weight(
    payload: WeightRecordIn,
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
    session: AsyncSession = Depends(get_db),
) -> Envelope[WeightRecordOut]:
    data = await weight_service.create_weight(session, user.id, payload)
    return ok(data, request_id=request_id)


@router.delete("/weight/{id}", response_model=Envelope[WeightDeleteData], summary="删除体重记录")
async def delete_weight(
    id: int,
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
    session: AsyncSession = Depends(get_db),
) -> Envelope[WeightDeleteData]:
    data = await weight_service.delete_weight(session, user.id, id)
    return ok(data, request_id=request_id)


@router.get("/weight/trend", response_model=Envelope[WeightTrendData], summary="体重趋势")
async def weight_trend(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
    session: AsyncSession = Depends(get_db),
) -> Envelope[WeightTrendData]:
    data = await weight_service.get_trend(session, user.id, start_date, end_date)
    return ok(data, request_id=request_id)
