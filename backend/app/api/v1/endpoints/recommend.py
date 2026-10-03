"""饭点决策接口（openapi: /api/ai/recommend）——Phase 2 BE4c 实现域。

从 `ai.py` 拆出，避免对话与推荐两组端点争抢同一文件。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_current_user, get_request_id
from app.core.config import get_settings
from app.db.session import get_db
from app.schemas import AiRecommendData, AiRecommendIn, Envelope
from app.schemas.common import ok
from app.services import recommend_service

router = APIRouter(tags=["AI"])


@router.post("/ai/recommend", response_model=Envelope[AiRecommendData], summary="饭点决策推荐")
async def ai_recommend(
    payload: AiRecommendIn,
    session: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[AiRecommendData]:
    """剩余额度内产出 2~3 个组合；健康等级写在 `reason` 前缀（绿/黄/红）。

    AI 不可用只降级文案，不返回 6001（推荐必须始终可用）。
    """
    options = await recommend_service.recommend(
        session,
        get_settings(),
        int(user.id),
        payload.meal_type,
        location=payload.location,
        budget=payload.budget,
    )
    return ok(AiRecommendData(options=options), request_id=request_id)
