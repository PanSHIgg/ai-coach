"""记录域接口（openapi: /api/food/search、/api/meal/*、/api/sport*，共 8 接口）。

BE3 真实实现：食物 tsvector 检索、饮食记录 CRUD（写后重算当日）、运动记录。
/api/meal/recognize（拍照识别）属 Phase 2 BE4a，本阶段保留 stub。
"""

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_current_user, get_request_id
from app.core.errors import AppException
from app.db.session import get_db
from app.schemas import Envelope
from app.schemas.common import ErrorCode, ok
from app.schemas.record import (
    FoodSearchData,
    FoodSearchIn,
    MealCreatedData,
    MealCreateIn,
    MealDeleteData,
    MealPageData,
    MealUpdateIn,
    RecognizeData,
    RecognizedItem,
    SportCreatedData,
    SportIn,
    SportPageData,
)
from app.services import record_service

router = APIRouter(tags=["记录"])


def _parse_date(value: str | None) -> date | None:
    """查询参数 date（YYYY-MM-DD）→ date；格式非法抛 2001。"""
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise AppException(ErrorCode.VALIDATION_ERROR, "date 格式应为 YYYY-MM-DD") from exc


@router.post(
    "/food/search",
    response_model=Envelope[FoodSearchData],
    summary="食物搜索（PG 全文检索 + 别名）",
)
async def search_food(
    payload: FoodSearchIn,
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
    session: AsyncSession = Depends(get_db),
) -> Envelope[FoodSearchData]:
    data = await record_service.search_food(session, payload.keyword, payload.limit)
    return ok(data, request_id=request_id)


@router.post("/meal/recognize", response_model=Envelope[RecognizeData], summary="拍照识别食物")
async def recognize_meal(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[RecognizeData]:
    # TODO(Phase2 BE4a): COS 上传 + 视觉 API 识别（本阶段保留 stub）
    _image = await request.body()
    data = RecognizeData(
        request_id=request_id or uuid.uuid4().hex,
        items=[
            RecognizedItem(food_id=208, name="清蒸鱼", confidence=0.92, amount_g=150, calories=180),
            RecognizedItem(food_id=512, name="红烧肉", confidence=0.61, amount_g=100, calories=320),
        ],
        need_confirm=True,
    )
    return ok(data, request_id=request_id)


@router.post("/meal", response_model=Envelope[MealCreatedData], summary="新增饮食记录")
async def create_meal(
    payload: MealCreateIn,
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
    session: AsyncSession = Depends(get_db),
) -> Envelope[MealCreatedData]:
    data = await record_service.create_meal(session, user.id, payload)
    return ok(data, request_id=request_id)


@router.put("/meal/{id}", response_model=Envelope[MealCreatedData], summary="编辑饮食记录")
async def update_meal(
    id: int,
    payload: MealUpdateIn,
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
    session: AsyncSession = Depends(get_db),
) -> Envelope[MealCreatedData]:
    data = await record_service.update_meal(session, user.id, id, payload)
    return ok(data, request_id=request_id)


@router.delete("/meal/{id}", response_model=Envelope[MealDeleteData], summary="删除饮食记录")
async def delete_meal(
    id: int,
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
    session: AsyncSession = Depends(get_db),
) -> Envelope[MealDeleteData]:
    data = await record_service.delete_meal(session, user.id, id)
    return ok(data, request_id=request_id)


@router.get("/meal/list", response_model=Envelope[MealPageData], summary="饮食记录列表")
async def list_meals(
    date: str | None = Query(default=None),
    meal_type: int | None = Query(default=None, ge=1, le=4),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
    session: AsyncSession = Depends(get_db),
) -> Envelope[MealPageData]:
    data = await record_service.list_meals(
        session, user.id, _parse_date(date), meal_type, page, page_size
    )
    return ok(data, request_id=request_id)


@router.post("/sport", response_model=Envelope[SportCreatedData], summary="新增运动记录")
async def create_sport(
    payload: SportIn,
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
    session: AsyncSession = Depends(get_db),
) -> Envelope[SportCreatedData]:
    data = await record_service.create_sport(session, user.id, payload)
    return ok(data, request_id=request_id)


@router.get("/sport/list", response_model=Envelope[SportPageData], summary="运动记录列表")
async def list_sports(
    date: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
    session: AsyncSession = Depends(get_db),
) -> Envelope[SportPageData]:
    data = await record_service.list_sports(session, user.id, _parse_date(date), page, page_size)
    return ok(data, request_id=request_id)
