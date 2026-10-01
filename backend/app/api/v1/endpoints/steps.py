"""步数同步接口（openapi: /api/steps/sync，BE2b 归属本模块）。

从 records.py 拆出以隔离并行改动（BE2b 与 BE3 分属不同任务）。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_current_user, get_request_id
from app.db.session import get_db
from app.schemas import Envelope
from app.schemas.common import ok
from app.schemas.record import StepsSyncData
from app.schemas.record import StepsSyncIn as _StepsSyncIn
from app.services import steps as steps_service

router = APIRouter(tags=["记录"])


class StepsSyncIn(_StepsSyncIn):
    """/api/steps/sync 请求体（F-09 扩展）。

    契约公共请求体 `StepsSyncIn` 定义于 `app/schemas/record.py`（本次可写文件白名单外），
    此处以子类**追加**两个可选微信运动字段（encrypted_data/iv），保持 OpenAPI
    schema 名与契约一致且不触达白名单外文件。无凭证 / 解密失败 → 服务层明确降级（不伪造）。
    """

    encrypted_data: str | None = None  # 微信运动加密数据（uni.getWeRunData）
    iv: str | None = None  # 加密初始向量


@router.post("/steps/sync", response_model=Envelope[StepsSyncData], summary="同步步数（NEAT 校准）")
async def sync_steps(
    payload: StepsSyncIn,
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
    session: AsyncSession = Depends(get_db),
) -> Envelope[StepsSyncData]:
    # 写 step_record（(user_id,record_date) 幂等 upsert）+ 逐时 MET 校准 + 重算当日快照。
    # 有微信运动加密数据且凭证齐备 → 解密取真实步数；否则按传入 steps 降级（不伪造）。
    data = await steps_service.sync_steps(
        session,
        user.id,
        payload.date,
        payload.steps,
        payload.hourly,
        encrypted_data=payload.encrypted_data,
        iv=payload.iv,
    )
    return ok(data, request_id=request_id)
