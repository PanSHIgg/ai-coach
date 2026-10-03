"""步数接口（openapi: /api/steps/sync、/api/steps/trend，BE2b 归属本模块）。

从 records.py 拆出以隔离并行改动（BE2b 与 BE3 分属不同任务）。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_current_user, get_request_id
from app.db.session import get_db
from app.schemas import Envelope
from app.schemas.common import ok
from app.schemas.record import StepsSyncData, StepsSyncIn, StepsTrendData
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
    # 有微信运动加密数据 → 用**本用户本次登录**的 session_key 解密（含 watermark 校验）；
    # 链路不满足则按传入 steps 明确降级，来源在响应 steps_source（1/2/3）里如实回传。
    # 解密成功时顺带回填 stepInfoList 的 ≤31 天历史（回填天数见 backfilled_days）。
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


@router.get("/steps/trend", response_model=Envelope[StepsTrendData], summary="步数历史曲线（按天）")
async def get_steps_trend(
    # 上限 31 与微信运动 stepInfoList 条数一致（契约 minimum 1 / maximum 31）；越界 → 422/2001
    days: int = Query(default=31, ge=1, le=steps_service.WERUN_MAX_DAYS),
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
    session: AsyncSession = Depends(get_db),
) -> Envelope[StepsTrendData]:
    # 步数曲线的唯一数据源：直读 step_record（**不是** daily_snapshot —— 历史日期普遍没有快照，
    # 为画步数去补快照会把 intake/tee/deficit 伪造成 0）。区间 [今天-days+1, 今天]、日期升序，
    # 没有记录的日期不出现（不补零）。user_id 条件在 service 里下推，行级隔离（AGENTS §7.3）。
    data = await steps_service.get_step_trend(session, user.id, days)
    return ok(data, request_id=request_id)
