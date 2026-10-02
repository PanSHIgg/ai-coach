"""AI 域接口（openapi: /api/ai/chat、/api/ai/times）——Phase 2 BE4b 实现域。

注：`/api/ai/recommend` 已拆到 `endpoints/recommend.py`（BE4c），避免两代理争抢同一文件。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_current_user, get_request_id
from app.db.session import get_db
from app.schemas import (
    AiChatData,
    AiChatIn,
    AiTimesData,
    Envelope,
    WeeklyCommentData,
    WeeklyCommentIn,
)
from app.schemas.common import ok
from app.services import ai_service, voice_service
from app.services.voice_service import VoiceTranscribeData, VoiceTranscribeIn

router = APIRouter(tags=["AI"])


@router.post("/ai/chat", response_model=Envelope[AiChatData], summary="AI 对话（校验剩余次数）")
async def ai_chat(
    payload: AiChatIn,
    session: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[AiChatData]:
    """次数不足 → 4001；LLM 不可用/超时 → 6001（由 AppException 转 envelope）。"""
    result = await ai_service.chat(
        session,
        user_id=int(user.id),
        session_id=payload.session_id,
        message=payload.message,
    )
    return ok(
        AiChatData(
            reply=result.reply,
            intent=result.intent,
            times_left=result.times_left,
            references=result.references,
        ),
        request_id=request_id,
    )


@router.get("/ai/times", response_model=Envelope[AiTimesData], summary="查询剩余对话次数")
async def get_ai_times(
    session: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[AiTimesData]:
    return ok(
        AiTimesData(times_left=await ai_service.get_times_left(session, int(user.id))),
        request_id=request_id,
    )


@router.post(
    "/ai/weekly-comment", response_model=Envelope[WeeklyCommentData], summary="AI 周点评（周报）"
)
async def weekly_comment(
    payload: WeeklyCommentIn | None = None,
    session: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[WeeklyCommentData]:
    """按周聚合热量/步数/体重，生成 AI 点评（无 Key 落本地模板）。"""
    data = await ai_service.weekly_comment(
        session, user_id=int(user.id), week=payload.week if payload else None
    )
    return ok(data, request_id=request_id)


@router.post(
    "/ai/voice-transcribe",
    response_model=Envelope[VoiceTranscribeData],
    summary="语音转文字",
)
async def voice_transcribe(
    payload: VoiceTranscribeIn,
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[VoiceTranscribeData]:
    """未配置 ASR 时明确降级（provider="disabled"、text=""），HTTP 200 不 500。"""
    data = await voice_service.transcribe(payload.audio_base64, payload.format)
    return ok(data, request_id=request_id)
