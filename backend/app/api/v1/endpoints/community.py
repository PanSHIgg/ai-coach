"""社区域接口（Phase 4 真实现）。

契约：/api/invite*、/api/community/*（BE7a 动态 / BE7b 五种社交）。
统一 envelope + 错误码 + Bearer JWT；写操作落库。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_current_user, get_request_id
from app.core.errors import AppException
from app.db.session import get_db
from app.models import Invite, User, UserBenefit
from app.schemas import (
    BattleCreateIn,
    BattleItem,
    BattleJoinData,
    BattleJoinIn,
    BattlePageData,
    BenefitInfo,
    ChallengeItem,
    ChallengeJoinData,
    ChallengeLeaderboardData,
    ChallengePageData,
    CommentPageData,
    CommunityCommentIn,
    CommunityCommentOut,
    CommunityPostCreated,
    CommunityPostIn,
    CommunityPostOut,
    Envelope,
    ExperiencePageData,
    GroupCheckinData,
    GroupItem,
    GroupJoinData,
    GroupPageData,
    InviteData,
    InviteIn,
    InviteProgressData,
    LeaderboardData,
    LikeData,
    NextTier,
    PostDeleteData,
    PostPageData,
    SuperviseMatchIn,
    SuperviseOut,
    SuperviseRecordsData,
    SuperviseRemindData,
)
from app.schemas.common import ErrorCode, ok
from app.services import community_service as svc

router = APIRouter(tags=["社区"])

# 邀请上限：单账号最多有效邀请人数（超出 7001/409）【假设】
MAX_INVITEES = 5


# ---- 邀请 ----

def _invite_code(user_id: int) -> str:
    """确定性邀请码（无需额外列持久化）。"""
    return f"INV-{user_id}"


async def _parse_inviter(code: str) -> int:
    """从邀请码解析邀请人 id；非法码 2001。"""
    prefix = "INV-"
    if not code.startswith(prefix) or not code[len(prefix):].isdigit():
        raise AppException(ErrorCode.VALIDATION_ERROR, "邀请码无效")
    return int(code[len(prefix):])


@router.post("/invite", response_model=Envelope[InviteData], summary="创建邀请/绑定")
async def create_invite(
    payload: InviteIn | None = None,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[InviteData]:
    """无 invite_code → 返回我的邀请码；带 invite_code → 绑定邀请关系（落库，上限 7001）。"""
    if not payload or not payload.invite_code:
        return ok(
            InviteData(
                bound=False,
                invite_code=_invite_code(user.id),
                poster_url=f"https://cos.example.com/invite/{user.id}.png",
            ),
            request_id=request_id,
        )
    inviter_id = await _parse_inviter(payload.invite_code)
    inviter = await session.scalar(select(User.id).where(User.id == inviter_id))
    if inviter is None:
        raise AppException(ErrorCode.NOT_FOUND, "邀请人不存在")
    if inviter_id == user.id:
        raise AppException(ErrorCode.VALIDATION_ERROR, "不能绑定自己的邀请码")
    existing = await session.scalar(select(Invite.id).where(Invite.invitee_id == user.id))
    if existing is not None:
        raise AppException(ErrorCode.VALIDATION_ERROR, "你已绑定过邀请关系")
    invitee_count = await session.scalar(
        select(func.count()).select_from(Invite).where(Invite.inviter_id == inviter_id)
    )
    if int(invitee_count or 0) >= MAX_INVITEES:
        raise AppException(ErrorCode.INVITE_LIMIT, "邀请已达上限")
    session.add(Invite(inviter_id=inviter_id, invitee_id=user.id, status=1))
    await session.commit()
    return ok(InviteData(bound=True), request_id=request_id)


@router.get("/invite/progress", response_model=Envelope[InviteProgressData], summary="邀请进度")
async def get_invite_progress(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[InviteProgressData]:
    """邀请人数 + 下一档奖励 + 当前权益（落库统计）。"""
    invitee_count = await session.scalar(
        select(func.count()).select_from(Invite).where(Invite.inviter_id == user.id)
    )
    count = int(invitee_count or 0)
    next_need = 2 if count < 2 else (5 if count < 5 else 10)
    benefit = (
        await session.execute(select(UserBenefit).where(UserBenefit.user_id == user.id))
    ).scalar_one_or_none()
    return ok(
        InviteProgressData(
            invitee_count=count,
            next_tier=NextTier(need=max(next_need - count, 0), reward="进阶版90天"),
            benefit=BenefitInfo(
                tier=benefit.tier if benefit else 0,
                valid_to=benefit.valid_to if benefit else None,
            ),
            poster_url=f"https://cos.example.com/invite/{user.id}.png",
        ),
        request_id=request_id,
    )


# ---- BE7a 动态 ----

@router.get("/community/post/list", response_model=Envelope[PostPageData], summary="社区动态列表")
async def list_community_posts(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    post_type: int | None = Query(default=None, ge=1, le=3),
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[PostPageData]:
    data = await svc.list_posts(session, user.id, page, page_size, post_type)
    return ok(data, request_id=request_id)


@router.post("/community/post", response_model=Envelope[CommunityPostCreated], summary="发动态")
async def create_community_post(
    payload: CommunityPostIn,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[CommunityPostCreated]:
    data = await svc.create_post(session, user.id, payload)
    return ok(data, request_id=request_id)


@router.get("/community/post/{id}", response_model=Envelope[CommunityPostOut], summary="动态详情")
async def get_community_post(
    id: int,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[CommunityPostOut]:
    data = await svc.get_post(session, user.id, id)
    return ok(data, request_id=request_id)


@router.delete("/community/post/{id}", response_model=Envelope[PostDeleteData], summary="删除动态")
async def delete_community_post(
    id: int,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[PostDeleteData]:
    data = await svc.delete_post(session, user.id, id)
    return ok(data, request_id=request_id)


@router.post("/community/post/{id}/like", response_model=Envelope[LikeData], summary="点赞动态")
async def like_community_post(
    id: int,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[LikeData]:
    data = await svc.like_post(session, user.id, id)
    return ok(data, request_id=request_id)


@router.delete("/community/post/{id}/like", response_model=Envelope[LikeData], summary="取消点赞")
async def unlike_community_post(
    id: int,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[LikeData]:
    data = await svc.unlike_post(session, user.id, id)
    return ok(data, request_id=request_id)


@router.get(
    "/community/post/{id}/comment/list",
    response_model=Envelope[CommentPageData],
    summary="动态评论列表",
)
async def list_post_comments(
    id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[CommentPageData]:
    data = await svc.list_comments(session, page, page_size, id)
    return ok(data, request_id=request_id)


@router.post(
    "/community/post/{id}/comment",
    response_model=Envelope[CommunityCommentOut],
    summary="发表评论",
)
async def create_post_comment(
    id: int,
    payload: CommunityCommentIn,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[CommunityCommentOut]:
    data = await svc.create_comment(session, user.id, id, payload)
    return ok(data, request_id=request_id)


@router.get(
    "/community/experience/list",
    response_model=Envelope[ExperiencePageData],
    summary="同款减友经验列表",
)
async def list_experience(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[ExperiencePageData]:
    data = await svc.list_experience(session, page, page_size)
    return ok(data, request_id=request_id)


# ---- BE7b 监督搭子 ----

@router.get("/community/supervise", response_model=Envelope[SuperviseOut], summary="我的监督搭子")
async def get_supervise(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[SuperviseOut]:
    data = await svc.get_my_supervise(session, user.id)
    if data is None:
        raise AppException(ErrorCode.NOT_FOUND, "尚无监督搭子")
    return ok(data, request_id=request_id)


@router.post(
    "/community/supervise/match", response_model=Envelope[SuperviseOut], summary="匹配搭子"
)
async def match_supervise(
    payload: SuperviseMatchIn | None = None,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[SuperviseOut]:
    data = await svc.match_supervise(session, user.id, payload or SuperviseMatchIn())
    return ok(data, request_id=request_id)


@router.post(
    "/community/supervise/{id}/remind",
    response_model=Envelope[SuperviseRemindData],
    summary="提醒搭子打卡",
)
async def remind_supervise(
    id: int,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[SuperviseRemindData]:
    data = await svc.remind_partner(session, user.id, id)
    return ok(data, request_id=request_id)


@router.get(
    "/community/supervise/{id}/records",
    response_model=Envelope[SuperviseRecordsData],
    summary="互看记录",
)
async def supervise_records(
    id: int,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[SuperviseRecordsData]:
    data = await svc.partner_records(session, user.id, id)
    return ok(data, request_id=request_id)


# ---- BE7b 兴趣社群 ----

@router.get("/community/group/list", response_model=Envelope[GroupPageData], summary="社群列表")
async def list_groups(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[GroupPageData]:
    data = await svc.list_groups(session, page, page_size)
    return ok(data, request_id=request_id)


@router.get("/community/group/{id}", response_model=Envelope[GroupItem], summary="社群详情")
async def get_group(
    id: int,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[GroupItem]:
    data = await svc.get_group(session, id)
    return ok(data, request_id=request_id)


@router.post(
    "/community/group/{id}/join", response_model=Envelope[GroupJoinData], summary="加入社群"
)
async def join_group(
    id: int,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[GroupJoinData]:
    data = await svc.join_group(session, id)
    return ok(data, request_id=request_id)


@router.post(
    "/community/group/{id}/checkin", response_model=Envelope[GroupCheckinData], summary="社群打卡"
)
async def checkin_group(
    id: int,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[GroupCheckinData]:
    data = await svc.checkin_group(session, user.id, id)
    return ok(data, request_id=request_id)


# ---- BE7b 约战 ----

@router.post("/community/battle", response_model=Envelope[BattleItem], summary="发起约战")
async def create_battle(
    payload: BattleCreateIn,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[BattleItem]:
    data = await svc.create_battle(session, user.id, payload)
    return ok(data, request_id=request_id)


@router.get("/community/battle/list", response_model=Envelope[BattlePageData], summary="约战列表")
async def list_battles(
    city: str | None = Query(default=None),
    status: int | None = Query(default=None, ge=1, le=4),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[BattlePageData]:
    data = await svc.list_battles(session, city, status, page, page_size)
    return ok(data, request_id=request_id)


@router.post("/community/battle/join", response_model=Envelope[BattleJoinData], summary="加入约战")
async def join_battle(
    payload: BattleJoinIn,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[BattleJoinData]:
    data = await svc.join_battle(session, payload.battle_id)
    return ok(data, request_id=request_id)


# ---- BE7b 挑战赛 ----

@router.get(
    "/community/challenge/list", response_model=Envelope[ChallengePageData], summary="挑战赛列表"
)
async def list_challenges(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[ChallengePageData]:
    data = await svc.list_challenges(session, user.id, page, page_size)
    return ok(data, request_id=request_id)


@router.get(
    "/community/challenge/{id}", response_model=Envelope[ChallengeItem], summary="挑战赛详情"
)
async def get_challenge(
    id: int,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[ChallengeItem]:
    data = await svc.get_challenge(session, user.id, id)
    return ok(data, request_id=request_id)


@router.post(
    "/community/challenge/{id}/join",
    response_model=Envelope[ChallengeJoinData],
    summary="参加挑战赛",
)
async def join_challenge(
    id: int,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[ChallengeJoinData]:
    data = await svc.join_challenge(session, user.id, id)
    return ok(data, request_id=request_id)


@router.get(
    "/community/challenge/{id}/leaderboard",
    response_model=Envelope[ChallengeLeaderboardData],
    summary="挑战赛排行榜",
)
async def challenge_leaderboard(
    id: int,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[ChallengeLeaderboardData]:
    data = await svc.challenge_leaderboard(session, id)
    return ok(data, request_id=request_id)


# ---- BE7b 热量控制榜 ----

@router.get(
    "/community/leaderboard", response_model=Envelope[LeaderboardData], summary="热量控制榜"
)
async def get_leaderboard(
    period_type: int = Query(default=2, ge=1, le=3),
    period_key: str | None = Query(default=None),
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    request_id: str | None = Depends(get_request_id),
) -> Envelope[LeaderboardData]:
    data = await svc.get_leaderboard(session, period_type, period_key)
    return ok(data, request_id=request_id)
