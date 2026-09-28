"""社区域接口（openapi: /api/invite、/api/invite/progress、/api/community/post/list、/api/community/post、/api/community/battle/list、/api/community/battle/join）。"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query

from app.api.deps import CurrentUser, get_current_user, get_request_id
from app.schemas import (
    BattleItem,
    BattleJoinData,
    BattleJoinIn,
    BenefitInfo,
    CommunityPostIn,
    CommunityPostOut,
    Envelope,
    InviteData,
    InviteIn,
    InviteProgressData,
    NextTier,
    PageMeta,
    UserBrief,
)
from app.schemas.community import BattlePageData, CommunityPostCreated, PostPageData
from app.schemas.common import ok

router = APIRouter(tags=["社区"])


@router.post("/invite", response_model=Envelope[InviteData], summary="创建邀请/绑定")
async def create_invite(
    payload: InviteIn | None = None,
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[InviteData]:
    # TODO(Phase1): 无 invite_code 生成我的邀请码；有则绑定（被邀请人 1 次拍照记录算有效；上限 7001）
    if payload and payload.invite_code:
        data = InviteData(bound=True)
    else:
        data = InviteData(bound=False, invite_code="INV-1001-XYZ", poster_url="https://cos.example.com/invite/1001.png")
    return ok(data, request_id=request_id)


@router.get("/invite/progress", response_model=Envelope[InviteProgressData], summary="邀请进度与权益")
async def get_invite_progress(
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[InviteProgressData]:
    # TODO(Phase1): invite 表统计 + user_benefit 权益（发放为次日定时任务）
    data = InviteProgressData(
        invitee_count=1,
        next_tier=NextTier(need=2, reward="进阶版90天"),
        benefit=BenefitInfo(tier=0, valid_to=None),
        poster_url="https://cos.example.com/invite/1001.png",
    )
    return ok(data, request_id=request_id)


@router.get("/community/post/list", response_model=Envelope[PostPageData], summary="社区动态列表")
async def list_community_posts(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[PostPageData]:
    # TODO(Phase1): community_post 分页（仅审核通过 audit_status=1，created_at DESC）
    data = PostPageData(
        items=[
            CommunityPostOut(
                id=1,
                user=UserBrief(id=1002, nickname="减友B", avatar_url=None),
                content="今天午餐打卡清蒸鱼",
                images=[],
                like_count=3,
                comment_count=1,
                created_at=datetime.now(),
            )
        ],
        page=PageMeta(page=page, page_size=page_size, total=1),
    )
    return ok(data, request_id=request_id)


@router.post("/community/post", response_model=Envelope[CommunityPostCreated], summary="发动态")
async def create_community_post(
    payload: CommunityPostIn,
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[CommunityPostCreated]:
    # TODO(Phase1): 微信 msgSecCheck/imgSecCheck 内容安全 → 违规进审核队列
    data = CommunityPostCreated(id=2)
    return ok(data, request_id=request_id)


@router.get("/community/battle/list", response_model=Envelope[BattlePageData], summary="约战列表")
async def list_battles(
    city: str | None = Query(default=None),
    status: int | None = Query(default=None, ge=1, le=4),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[BattlePageData]:
    # TODO(Phase1): battle 表按城市/状态过滤（city, meet_at 索引）
    data = BattlePageData(
        items=[
            BattleItem(
                id=1,
                title="轻食约战·第1期",
                sport_name="轻食",
                merchant_id=88,
                city="上海",
                meet_at=datetime.now() + timedelta(days=3),
                need_count=2,
                join_count=1,
                status=1,
            )
        ],
        page=PageMeta(page=page, page_size=page_size, total=1),
    )
    return ok(data, request_id=request_id)


@router.post("/community/battle/join", response_model=Envelope[BattleJoinData], summary="加入约战")
async def join_battle(
    payload: BattleJoinIn,
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[BattleJoinData]:
    # TODO(Phase1): 满员校验 + join_count 原子自增；不存在返回 3001
    data = BattleJoinData(battle_id=payload.battle_id, joined=True, join_count=2)
    return ok(data, request_id=request_id)
