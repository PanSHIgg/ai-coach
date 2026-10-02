"""报告接口（openapi: /api/report/export、/api/report/weekly）。

本文件为**协议层骨架**（Wave A 地基）：参数校验 + schema 组装 + 调用 service；
业务逻辑在 `app/services/report_service.py`（Wave B feature 代理填充实现）。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_current_user, get_request_id
from app.db.session import get_db
from app.schemas import Envelope
from app.schemas.common import ok
from app.schemas.report import ReportExportData, ReportExportIn, WeeklyReportData
from app.services import report_service

router = APIRouter(tags=["报告"])


@router.post("/report/export", response_model=Envelope[ReportExportData], summary="报告导出（csv）")
async def export_report(
    payload: ReportExportIn,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[ReportExportData]:
    data = await report_service.export_report(
        session, user_id=int(user.id), payload=payload
    )
    return ok(data, request_id=request_id)


@router.get(
    "/report/weekly",
    response_model=Envelope[WeeklyReportData],
    summary="热量控制周报（缺口/步数/体重趋势 + AI 点评）",
)
async def get_weekly_report(
    week: str | None = Query(default=None, max_length=16),
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[WeeklyReportData]:
    data = await report_service.weekly_report(session, user_id=int(user.id), week=week)
    return ok(data, request_id=request_id)