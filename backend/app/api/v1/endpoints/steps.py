"""步数同步接口（openapi: /api/steps/sync，BE2b 归属本模块）。

从 records.py 拆出以隔离并行改动（BE2b 与 BE3 分属不同任务）。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_current_user, get_request_id
from app.db.session import get_db
from app.schemas import Envelope
from app.schemas.common import ok
from app.schemas.record import StepsSyncData, StepsSyncIn
from app.services import steps as steps_service

router = APIRouter(tags=["记录"])


@router.post("/steps/sync", response_model=Envelope[StepsSyncData], summary="同步步数（NEAT 校准）")
async def sync_steps(
    payload: StepsSyncIn,
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
    session: AsyncSession = Depends(get_db),
) -> Envelope[StepsSyncData]:
    # 写 step_record（(user_id,record_date) 幂等 upsert）+ 逐时 MET 校准 + 重算当日快照。
    data = await steps_service.sync_steps(
        session, user.id, payload.date, payload.steps, payload.hourly
    )
    return ok(data, request_id=request_id)
