"""隐私设置接口（openapi: /api/privacy GET / PUT）。

本文件为**协议层骨架**（Wave A 地基）：参数校验 + schema 组装 + 调用 service；
业务逻辑在 `app/services/privacy_service.py`（Wave B feature 代理填充实现）。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_current_user, get_request_id
from app.db.session import get_db
from app.schemas import Envelope
from app.schemas.common import ok
from app.schemas.privacy import PrivacyData, PrivacyIn
from app.services import privacy_service

router = APIRouter(tags=["隐私"])


@router.get("/privacy", response_model=Envelope[PrivacyData], summary="读取隐私设置")
async def get_privacy(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[PrivacyData]:
    data = await privacy_service.get_privacy(session, user_id=int(user.id))
    return ok(data, request_id=request_id)


@router.put("/privacy", response_model=Envelope[PrivacyData], summary="更新隐私设置（部分字段）")
async def update_privacy(
    payload: PrivacyIn,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[PrivacyData]:
    data = await privacy_service.update_privacy(session, user_id=int(user.id), payload=payload)
    return ok(data, request_id=request_id)