"""AI 域接口（openapi: /api/ai/chat、/api/ai/times、/api/ai/recommend）。"""

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, get_current_user, get_request_id
from app.schemas import AiChatData, AiChatIn, AiRecommendData, AiRecommendIn, AiTimesData, Envelope, RecommendOption
from app.schemas.common import ok

router = APIRouter(tags=["AI"])

# TODO(Phase1-2): 接 app/ai（另一代理所有）——对话/RAG/视觉；AI 不可用降级 FAQ（6001）。


@router.post("/ai/chat", response_model=Envelope[AiChatData], summary="AI 对话（校验剩余次数）")
async def ai_chat(
    payload: AiChatIn,
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[AiChatData]:
    # TODO(Phase1): 次数校验（4001）→ LLM 调用（6001 降级）→ ai_dialog 落库
    data = AiChatData(
        reply="建议先喝一杯水，15分钟还不饱再吃个水煮蛋或黄瓜，热量低还顶饱。",
        intent="hunger_rescue",
        times_left=9,
        references=["knowledge:1203"],
    )
    return ok(data, request_id=request_id)


@router.get("/ai/times", response_model=Envelope[AiTimesData], summary="查询剩余对话次数")
async def get_ai_times(
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[AiTimesData]:
    # TODO(Phase1): user_benefit.ai_times_left
    return ok(AiTimesData(times_left=9), request_id=request_id)


@router.post("/ai/recommend", response_model=Envelope[AiRecommendData], summary="饭点决策推荐")
async def ai_recommend(
    payload: AiRecommendIn,
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[AiRecommendData]:
    # TODO(Phase2): 结合剩余额度/地理位置/商家 SKU 推荐
    data = AiRecommendData(
        options=[RecommendOption(food_id=208, name="清蒸鱼+杂粮饭", calories=450, reason="高蛋白低GI，剩余额度充足", merchant_id=88)]
    )
    return ok(data, request_id=request_id)
