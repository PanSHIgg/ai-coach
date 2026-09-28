"""用户档案域接口（openapi: /api/body-profile POST/GET）。"""

from datetime import datetime

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, get_current_user, get_request_id
from app.schemas import BodyProfileIn, BodyProfileOut, Envelope
from app.schemas.common import ok

router = APIRouter(tags=["用户档案"])


@router.post(
    "/body-profile",
    response_model=Envelope[BodyProfileOut],
    summary="创建/更新身体档案",
)
async def upsert_body_profile(
    payload: BodyProfileIn,
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[BodyProfileOut]:
    # TODO(Phase1): 落库 body_profile + 服务端计算 BMR/目标热量（P0 stub 对齐 mock）
    now = datetime.now()
    data = BodyProfileOut(
        id=1,
        bmr=1644.0,
        target_calories=2300,
        created_at=now,
        updated_at=now,
        **payload.model_dump(),
    )
    return ok(data, request_id=request_id)


@router.get(
    "/body-profile",
    response_model=Envelope[BodyProfileOut | None],
    summary="查询身体档案",
)
async def get_body_profile(
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[BodyProfileOut | None]:
    # TODO(Phase1): 按 user_id 查 body_profile；未创建时 data=None（契约允许）
    return ok(None, request_id=request_id)
