"""记录域接口（openapi: /api/food/search、/api/meal/*、/api/sport*、/api/steps/sync，共 9 接口）。"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import CurrentUser, get_current_user, get_request_id
from app.schemas import Envelope
from app.schemas.common import PageMeta, ok
from app.schemas.record import (
    FoodItem,
    FoodSearchData,
    FoodSearchIn,
    MealCreateIn,
    MealCreatedData,
    MealDeleteData,
    MealPageData,
    MealRecordOut,
    MealUpdateIn,
    RecognizeData,
    RecognizedItem,
    SportCreatedData,
    SportIn,
    SportPageData,
    SportRecordOut,
    StepsSyncData,
    StepsSyncIn,
)

router = APIRouter(tags=["记录"])


@router.post("/food/search", response_model=Envelope[FoodSearchData], summary="食物搜索（PG 全文检索 + 别名）")
async def search_food(
    payload: FoodSearchIn,
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[FoodSearchData]:
    # TODO(Phase1): food 表 tsvector + food_alias 检索（P0 stub 对齐 mock）
    data = FoodSearchData(
        items=[FoodItem(id=208, name="清蒸鱼", calories_100g=120.0, protein_100g=18.2, fat_100g=4.5, carb_100g=1.2, gi=0)],
        total=1,
    )
    return ok(data, request_id=request_id)


@router.post("/meal/recognize", response_model=Envelope[RecognizeData], summary="拍照识别食物")
async def recognize_meal(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[RecognizeData]:
    # TODO(Phase1): COS 上传 + 视觉 API 识别；multipart 解析需 python-multipart 依赖（P0 原始流 stub）
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
) -> Envelope[MealCreatedData]:
    # TODO(Phase1): 落 meal_record + 重算今日摄入/剩余（热量账户写入触发）
    data = MealCreatedData(id=9001, calories=180, today_intake=1418, today_left=682)
    return ok(data, request_id=request_id)


@router.put("/meal/{id}", response_model=Envelope[MealCreatedData], summary="编辑饮食记录")
async def update_meal(
    id: int,
    payload: MealUpdateIn,
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[MealCreatedData]:
    # TODO(Phase1): 行级隔离更新 + 重算今日摄入
    data = MealCreatedData(id=id, calories=200, today_intake=1438, today_left=662)
    return ok(data, request_id=request_id)


@router.delete("/meal/{id}", response_model=Envelope[MealDeleteData], summary="删除饮食记录")
async def delete_meal(
    id: int,
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[MealDeleteData]:
    # TODO(Phase1): 行级隔离删除 + 重算今日摄入
    data = MealDeleteData(id=id, deleted=True)
    return ok(data, request_id=request_id)


@router.get("/meal/list", response_model=Envelope[MealPageData], summary="饮食记录列表")
async def list_meals(
    date: str | None = Query(default=None),
    meal_type: int | None = Query(default=None, ge=1, le=4),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[MealPageData]:
    # TODO(Phase1): meal_record 分页（user_id 行级隔离，created_at DESC）
    data = MealPageData(
        items=[
            MealRecordOut(
                id=9001,
                meal_type=2,
                food_id=208,
                food_name="清蒸鱼",
                amount_g=150,
                calories=180,
                source=1,
                record_date=datetime.now().date(),
                created_at=datetime.now(),
            )
        ],
        page=PageMeta(page=page, page_size=page_size, total=1),
    )
    return ok(data, request_id=request_id)


@router.post("/sport", response_model=Envelope[SportCreatedData], summary="新增运动记录")
async def create_sport(
    payload: SportIn,
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[SportCreatedData]:
    # TODO(Phase1): 落 sport_record + 计入今日消耗
    data = SportCreatedData(id=3001, calories=320, today_burnt=320)
    return ok(data, request_id=request_id)


@router.get("/sport/list", response_model=Envelope[SportPageData], summary="运动记录列表")
async def list_sports(
    date: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[SportPageData]:
    # TODO(Phase1): sport_record 分页（行级隔离）
    now = datetime.now()
    data = SportPageData(
        items=[SportRecordOut(id=3001, sport_name="慢跑", met=8.0, duration_min=30, calories=320, record_at=now, created_at=now)],
        page=PageMeta(page=page, page_size=page_size, total=1),
    )
    return ok(data, request_id=request_id)


@router.post("/steps/sync", response_model=Envelope[StepsSyncData], summary="同步步数（NEAT 校准）")
async def sync_steps(
    payload: StepsSyncIn,
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[StepsSyncData]:
    # TODO(Phase1): 微信步数解密 + 逐时 MET 校准写 step_record
    data = StepsSyncData(neat_calibrated=520, met=3.8, delta_calories=80)
    return ok(data, request_id=request_id)
