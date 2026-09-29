"""埋点上报接口（openapi: /api/track，F3，归属本模块）。

地基由主 Agent 预建并挂入路由（AGENTS.md §4.2）；`track_service.record_events` 的实现
由 F3 后端子 Agent 填充。

允许匿名上报（登录前事件，如扫码进入）：契约侧 `security: []`，带有效 token 时关联 user_id。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_optional_user, get_request_id
from app.db.session import get_db
from app.schemas import Envelope, TrackData, TrackIn
from app.schemas.common import ok
from app.services import track_service

router = APIRouter(tags=["埋点"])


@router.post("/track", response_model=Envelope[TrackData], summary="埋点事件批量上报")
async def report_track(
    payload: TrackIn,
    user: CurrentUser | None = Depends(get_optional_user),
    request_id: str | None = Depends(get_request_id),
    session: AsyncSession = Depends(get_db),
) -> Envelope[TrackData]:
    data = await track_service.record_events(session, user.id if user else None, payload)
    return ok(data, request_id=request_id)
