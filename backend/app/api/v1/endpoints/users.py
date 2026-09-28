"""用户档案域接口（openapi: /api/body-profile POST/GET）。"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_current_user, get_request_id
from app.db.session import get_db
from app.schemas import BodyProfileIn, BodyProfileOut, Envelope
from app.schemas.common import ok
from app.services import user_service

router = APIRouter(tags=["用户档案"])


@router.post(
    "/body-profile",
    response_model=Envelope[BodyProfileOut],
    summary="创建/更新身体档案",
)
async def upsert_body_profile(
    payload: BodyProfileIn,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[BodyProfileOut]:
    """upsert body_profile（user_id 唯一），服务端计算 BMR 与每日热量预算。"""
    profile = await user_service.upsert_body_profile(session, user.id, payload)
    return ok(BodyProfileOut.model_validate(profile), request_id=request_id)


@router.get(
    "/body-profile",
    response_model=Envelope[BodyProfileOut | None],
    summary="查询身体档案",
)
async def get_body_profile(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[BodyProfileOut | None]:
    """按 user_id 查 body_profile；未创建时 data=None（契约允许）。"""
    profile = await user_service.get_body_profile(session, user.id)
    data = BodyProfileOut.model_validate(profile) if profile is not None else None
    return ok(data, request_id=request_id)
