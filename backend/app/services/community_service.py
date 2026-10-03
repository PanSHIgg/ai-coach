"""社区与社交服务（Phase 4）：动态 / 评论 / 点赞 / 监督 / 社群 / 约战 / 挑战赛 / 榜单。

BE7a 动态、BE7b 五种社交（监督搭子 / 兴趣社群 / 约战 / 挑战赛 / 热量控制榜 + 同款减友经验）。
内容安全统一走 `app.services.content_security`：违规内容入库 audit_status=0 并写 review 待审队列，
不直接对外展示。XSS：入库存原文，由渲染层（前端模板插值自动转义）负责，避免双重转义。

【假设】：
- community_group 无成员表：join 仅原子自增 member_count；checkin 以 post_type=3 动态沉淀打卡。
- leaderboard 有预聚合表但无写入方：读取时按期从 daily_snapshot 现算并 upsert。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppException
from app.models import (
    Battle,
    BattleParticipant,
    Challenge,
    ChallengeJoin,
    CommunityComment,
    CommunityGroup,
    CommunityLike,
    CommunityPost,
    DailySnapshot,
    Leaderboard,
    Merchant,
    Review,
    Supervise,
    User,
)
from app.schemas.auth import UserBrief
from app.schemas.common import ErrorCode, PageMeta
from app.schemas.community import (
    BattleCreateIn,
    BattleItem,
    BattleJoinData,
    BattlePageData,
    BattleQuitData,
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
    ExperienceItem,
    ExperiencePageData,
    GroupCheckinData,
    GroupItem,
    GroupJoinData,
    GroupPageData,
    LeaderboardData,
    LeaderboardEntry,
    LikeData,
    PostDeleteData,
    PostPageData,
    SuperviseMatchIn,
    SuperviseOut,
    SuperviseRecordItem,
    SuperviseRecordsData,
    SuperviseRemindData,
)
from app.services import content_security as sec

_TZ = timezone(timedelta(hours=8))
ANONYMOUS_BRIEF = UserBrief(id=0, nickname="匿名减友", avatar_url=None)


# 基础工具


def _brief(user: User | None) -> UserBrief:
    if user is None:
        return UserBrief(id=0, nickname="未知用户", avatar_url=None)
    return UserBrief(
        id=user.id, nickname=user.nickname or f"减友{user.id}", avatar_url=user.avatar_url
    )


async def _users_map(session: AsyncSession, user_ids: set[int]) -> dict[int, User]:
    ids = {uid for uid in user_ids if uid}
    if not ids:
        return {}
    rows = (await session.execute(select(User).where(User.id.in_(ids)))).scalars().all()
    return {u.id: u for u in rows}


async def _liked_ids(session: AsyncSession, user_id: int, post_ids: list[int]) -> set[int]:
    if not post_ids:
        return set()
    rows = await session.scalars(
        select(CommunityLike.post_id).where(
            CommunityLike.user_id == user_id, CommunityLike.post_id.in_(post_ids)
        )
    )
    return set(rows.all())


def _post_out(post: CommunityPost, author: User | None, liked: bool) -> CommunityPostOut:
    user = ANONYMOUS_BRIEF if post.anonymous else _brief(author)
    return CommunityPostOut(
        id=post.id,
        user=user,
        title=post.title,
        content=post.content or "",
        images=list(post.images or []),
        post_type=post.post_type,
        like_count=post.like_count,
        comment_count=post.comment_count,
        anonymous=bool(post.anonymous),
        liked=liked,
        created_at=post.created_at,
    )


async def _enqueue_review(
    session: AsyncSession, *, target_type: int, target_id: int, user_id: int,
    snapshot: str, result: int, reason: str | None,
) -> None:
    """违规内容写入审核队列（status=0 待审）。"""
    session.add(
        Review(
            target_type=target_type,
            target_id=target_id,
            user_id=user_id,
            content_snapshot=snapshot[:2000],
            sec_check_result=result,
            status=0,
            reject_reason=reason,
        )
    )


# BE7a 动态


async def create_post(
    session: AsyncSession, user_id: int, payload: CommunityPostIn
) -> CommunityPostCreated:
    """发动态：内容安全（文本+图）→ 违规 audit_status=0 入审核队列；正常 audit_status=1。"""
    check = await sec.scan(payload.content, payload.images)
    post = CommunityPost(
        user_id=user_id,
        title=payload.title,
        content=payload.content,
        images=payload.images,
        post_type=payload.post_type,
        anonymous=payload.anonymous,
        audit_status=1 if check.passed else 0,
    )
    session.add(post)
    await session.flush()
    if not check.passed:
        await _enqueue_review(
            session,
            target_type=1,
            target_id=post.id,
            user_id=user_id,
            snapshot=payload.content,
            result=check.result,
            reason=check.reason,
        )
    await session.commit()
    return CommunityPostCreated(id=post.id, audit_status=post.audit_status)


async def list_posts(
    session: AsyncSession,
    user_id: int,
    page: int,
    page_size: int,
    post_type: int | None = None,
) -> PostPageData:
    """动态分页：仅 audit_status=1，created_at DESC。"""
    conds = [CommunityPost.audit_status == 1]
    if post_type is not None:
        conds.append(CommunityPost.post_type == post_type)
    total = await session.scalar(select(func.count()).select_from(CommunityPost).where(*conds))
    rows = (
        (
            await session.execute(
                select(CommunityPost)
                .where(*conds)
                .order_by(CommunityPost.created_at.desc(), CommunityPost.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    authors = await _users_map(session, {p.user_id for p in rows})
    liked = await _liked_ids(session, user_id, [p.id for p in rows])
    return PostPageData(
        items=[_post_out(p, authors.get(p.user_id), p.id in liked) for p in rows],
        page=PageMeta(page=page, page_size=page_size, total=int(total or 0)),
    )


async def get_post(session: AsyncSession, user_id: int, post_id: int) -> CommunityPostOut:
    """动态详情：非审核通过时仅作者可见，否则 3001。"""
    post = (
        await session.execute(select(CommunityPost).where(CommunityPost.id == post_id))
    ).scalar_one_or_none()
    if post is None or (post.audit_status != 1 and post.user_id != user_id):
        raise AppException(ErrorCode.NOT_FOUND, "动态不存在或未通过审核")
    author = (await _users_map(session, {post.user_id})).get(post.user_id)
    liked = post.id in await _liked_ids(session, user_id, [post.id])
    return _post_out(post, author, liked)


async def delete_post(session: AsyncSession, user_id: int, post_id: int) -> PostDeleteData:
    """删除动态：仅作者本人（非作者 1002），不存在 3001。"""
    post = (
        await session.execute(select(CommunityPost).where(CommunityPost.id == post_id))
    ).scalar_one_or_none()
    if post is None:
        raise AppException(ErrorCode.NOT_FOUND, "动态不存在")
    if post.user_id != user_id:
        raise AppException(ErrorCode.FORBIDDEN, "只能删除自己的动态")
    await session.delete(post)
    await session.commit()
    return PostDeleteData(id=post_id, deleted=True)


async def like_post(session: AsyncSession, user_id: int, post_id: int) -> LikeData:
    """点赞：(post_id, user_id) 唯一，一人一赞（ON CONFLICT DO NOTHING 幂等）。"""
    post = (
        await session.execute(select(CommunityPost).where(CommunityPost.id == post_id))
    ).scalar_one_or_none()
    if post is None or post.audit_status != 1:
        raise AppException(ErrorCode.NOT_FOUND, "动态不存在")
    stmt = (
        pg_insert(CommunityLike)
        .values(post_id=post_id, user_id=user_id)
        .on_conflict_do_nothing(index_elements=["post_id", "user_id"])
        .returning(CommunityLike.id)
    )
    inserted = (await session.execute(stmt)).scalar_one_or_none()
    if inserted is not None:
        await session.execute(
            update(CommunityPost)
            .where(CommunityPost.id == post_id)
            .values(like_count=CommunityPost.like_count + 1)
        )
    count = await session.scalar(
        select(func.count()).select_from(CommunityLike).where(CommunityLike.post_id == post_id)
    )
    await session.commit()
    return LikeData(post_id=post_id, liked=True, like_count=int(count or 0))


async def unlike_post(session: AsyncSession, user_id: int, post_id: int) -> LikeData:
    """取消点赞：幂等，返回最新 like_count。"""
    post = (
        await session.execute(select(CommunityPost).where(CommunityPost.id == post_id))
    ).scalar_one_or_none()
    if post is None:
        raise AppException(ErrorCode.NOT_FOUND, "动态不存在")
    deleted = await session.execute(
        delete(CommunityLike).where(
            CommunityLike.post_id == post_id, CommunityLike.user_id == user_id
        )
    )
    if deleted.rowcount:
        await session.execute(
            update(CommunityPost)
            .where(CommunityPost.id == post_id)
            .values(like_count=func.greatest(CommunityPost.like_count - 1, 0))
        )
    count = await session.scalar(
        select(func.count()).select_from(CommunityLike).where(CommunityLike.post_id == post_id)
    )
    await session.commit()
    return LikeData(post_id=post_id, liked=False, like_count=int(count or 0))


async def list_comments(
    session: AsyncSession, page: int, page_size: int, post_id: int
) -> CommentPageData:
    """评论分页：仅 audit_status=1，created_at ASC。"""
    conds = [CommunityComment.post_id == post_id, CommunityComment.audit_status == 1]
    total = await session.scalar(select(func.count()).select_from(CommunityComment).where(*conds))
    rows = (
        (
            await session.execute(
                select(CommunityComment)
                .where(*conds)
                .order_by(CommunityComment.created_at.asc(), CommunityComment.id.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    authors = await _users_map(session, {c.user_id for c in rows})
    items = [
        CommunityCommentOut(
            id=c.id,
            user=ANONYMOUS_BRIEF if c.anonymous else _brief(authors.get(c.user_id)),
            content=c.content,
            anonymous=bool(c.anonymous),
            created_at=c.created_at,
        )
        for c in rows
    ]
    return CommentPageData(
        items=items, page=PageMeta(page=page, page_size=page_size, total=int(total or 0))
    )


async def create_comment(
    session: AsyncSession, user_id: int, post_id: int, payload: CommunityCommentIn
) -> CommunityCommentOut:
    """发表评论：内容安全 → 违规 audit_status=0 入审核队列（不计数、不展示）。"""
    post = (
        await session.execute(select(CommunityPost).where(CommunityPost.id == post_id))
    ).scalar_one_or_none()
    if post is None or post.audit_status != 1:
        raise AppException(ErrorCode.NOT_FOUND, "动态不存在")
    check = await sec.check_text(payload.content)
    comment = CommunityComment(
        post_id=post_id,
        user_id=user_id,
        content=payload.content,
        anonymous=payload.anonymous,
        audit_status=1 if check.passed else 0,
    )
    session.add(comment)
    await session.flush()
    if check.passed:
        await session.execute(
            update(CommunityPost)
            .where(CommunityPost.id == post_id)
            .values(comment_count=CommunityPost.comment_count + 1)
        )
    else:
        await _enqueue_review(
            session,
            target_type=2,
            target_id=comment.id,
            user_id=user_id,
            snapshot=payload.content,
            result=check.result,
            reason=check.reason,
        )
    await session.commit()
    author = (await _users_map(session, {user_id})).get(user_id)
    return CommunityCommentOut(
        id=comment.id,
        user=ANONYMOUS_BRIEF if comment.anonymous else _brief(author),
        content=comment.content,
        anonymous=bool(comment.anonymous),
        created_at=comment.created_at,
    )


async def list_experience(session: AsyncSession, page: int, page_size: int) -> ExperiencePageData:
    """同款减友经验（post_type=2 动态视图）。"""
    conds = [CommunityPost.audit_status == 1, CommunityPost.post_type == 2]
    total = await session.scalar(select(func.count()).select_from(CommunityPost).where(*conds))
    rows = (
        (
            await session.execute(
                select(CommunityPost)
                .where(*conds)
                .order_by(CommunityPost.created_at.desc(), CommunityPost.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    authors = await _users_map(session, {p.user_id for p in rows})
    items = [
        ExperienceItem(
            id=p.id,
            user=ANONYMOUS_BRIEF if p.anonymous else _brief(authors.get(p.user_id)),
            title=p.title,
            content=p.content or "",
            like_count=p.like_count,
            created_at=p.created_at,
        )
        for p in rows
    ]
    return ExperiencePageData(
        items=items, page=PageMeta(page=page, page_size=page_size, total=int(total or 0))
    )


# BE7b 监督搭子


async def _active_supervise(session: AsyncSession, user_id: int) -> Supervise | None:
    return (
        await session.execute(
            select(Supervise).where(
                Supervise.status == 1,
                (Supervise.user_a == user_id) | (Supervise.user_b == user_id),
            )
        )
    ).scalars().first()


async def _supervise_out(session: AsyncSession, sup: Supervise, user_id: int) -> SuperviseOut:
    partner_id = sup.user_b if sup.user_a == user_id else sup.user_a
    partner = (await _users_map(session, {partner_id})).get(partner_id)
    return SuperviseOut(
        id=sup.id,
        partner=_brief(partner),
        status=sup.status,
        days=sup.days,
        created_at=sup.created_at,
    )


async def get_my_supervise(session: AsyncSession, user_id: int) -> SuperviseOut | None:
    """我的监督搭子；无则返回 None。"""
    sup = await _active_supervise(session, user_id)
    if sup is None:
        return None
    return await _supervise_out(session, sup, user_id)


async def match_supervise(
    session: AsyncSession, user_id: int, payload: SuperviseMatchIn
) -> SuperviseOut:
    """匹配搭子：一人一对唯一（已有生效关系 2001）；缺 partner_id 时系统匹配未配对的减友。

    并发安全：DB 唯一约束仅 (user_a,user_b)，无法阻止「同一用户同时与两人」生效。
    故对双方用户行按 id 升序 FOR UPDATE 串行化后复查生效关系，再插入；唯一键冲突兜底转 2001。
    """
    if await _active_supervise(session, user_id) is not None:
        raise AppException(ErrorCode.VALIDATION_ERROR, "你已有监督搭子")
    partner_id = payload.partner_id
    if partner_id is None:
        partner_id = await _pick_unpaired_partner(session, user_id)
        if partner_id is None:
            raise AppException(ErrorCode.NOT_FOUND, "暂无可匹配的减友")
    elif partner_id == user_id:
        raise AppException(ErrorCode.VALIDATION_ERROR, "不能与自己配对")
    else:
        exists = await session.scalar(select(User.id).where(User.id == partner_id))
        if exists is None:
            raise AppException(ErrorCode.NOT_FOUND, "搭子不存在")
    a, b = sorted((user_id, partner_id))
    # 锁双方用户行（固定升序防死锁）→ 串行化同一用户的并发匹配
    await session.execute(
        select(User.id).where(User.id.in_((a, b))).order_by(User.id).with_for_update()
    )
    if await _active_supervise(session, user_id) is not None:
        raise AppException(ErrorCode.VALIDATION_ERROR, "你已有监督搭子")
    if await _active_supervise(session, partner_id) is not None:
        raise AppException(ErrorCode.VALIDATION_ERROR, "对方已有监督搭子")
    sup = Supervise(user_a=a, user_b=b, status=1, days=0)
    session.add(sup)
    try:
        await session.commit()
    except IntegrityError as exc:  # 双方互为对方并发匹配 → 唯一键冲突兜底
        await session.rollback()
        raise AppException(ErrorCode.VALIDATION_ERROR, "你已有监督搭子") from exc
    return await _supervise_out(session, sup, user_id)


async def _pick_unpaired_partner(session: AsyncSession, user_id: int) -> int | None:
    """挑一个未参与生效监督关系的其他用户。"""
    paired = select(Supervise.user_a).where(Supervise.status == 1).union(
        select(Supervise.user_b).where(Supervise.status == 1)
    )
    row = await session.execute(
        select(User.id)
        .where(User.id != user_id, User.id.notin_(paired))
        .order_by(User.id)
        .limit(1)
    )
    return row.scalar_one_or_none()


async def _ensure_member(session: AsyncSession, user_id: int, supervise_id: int) -> Supervise:
    sup = (
        await session.execute(select(Supervise).where(Supervise.id == supervise_id))
    ).scalar_one_or_none()
    if sup is None or user_id not in (sup.user_a, sup.user_b):
        raise AppException(ErrorCode.NOT_FOUND, "监督关系不存在")
    return sup


async def remind_partner(
    session: AsyncSession, user_id: int, supervise_id: int
) -> SuperviseRemindData:
    """提醒搭子打卡（仅关系成员）。"""
    sup = await _ensure_member(session, user_id, supervise_id)
    partner_id = sup.user_b if sup.user_a == user_id else sup.user_a
    partner = (await _users_map(session, {partner_id})).get(partner_id)
    name = _brief(partner).nickname
    return SuperviseRemindData(
        supervise_id=sup.id, reminded=True, message=f"已提醒 {name} 打卡"
    )


async def partner_records(
    session: AsyncSession, user_id: int, supervise_id: int
) -> SuperviseRecordsData:
    """互看记录：返回搭子近 7 天每日热量/步数/缺口。"""
    sup = await _ensure_member(session, user_id, supervise_id)
    partner_id = sup.user_b if sup.user_a == user_id else sup.user_a
    partner = (await _users_map(session, {partner_id})).get(partner_id)
    today = datetime.now(_TZ).date()
    start = today - timedelta(days=6)
    rows = (
        (
            await session.execute(
                select(DailySnapshot)
                .where(
                    DailySnapshot.user_id == partner_id,
                    DailySnapshot.snapshot_date >= start,
                    DailySnapshot.snapshot_date <= today,
                )
                .order_by(DailySnapshot.snapshot_date.desc())
            )
        )
        .scalars()
        .all()
    )
    items = [
        SuperviseRecordItem(
            date=r.snapshot_date.isoformat(),
            intake=float(r.intake or 0),
            steps=int(r.steps or 0),
            deficit=float(r.deficit or 0),
        )
        for r in rows
    ]
    return SuperviseRecordsData(supervise_id=sup.id, partner=_brief(partner), items=items)


# BE7b 兴趣社群


def _group_out(g: CommunityGroup) -> GroupItem:
    return GroupItem(
        id=g.id,
        name=g.name,
        category=g.category,
        member_count=g.member_count,
        city=g.city,
        created_at=g.created_at,
    )


async def list_groups(session: AsyncSession, page: int, page_size: int) -> GroupPageData:
    total = await session.scalar(select(func.count()).select_from(CommunityGroup))
    rows = (
        (
            await session.execute(
                select(CommunityGroup)
                .order_by(CommunityGroup.member_count.desc(), CommunityGroup.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return GroupPageData(
        items=[_group_out(g) for g in rows],
        page=PageMeta(page=page, page_size=page_size, total=int(total or 0)),
    )


async def get_group(session: AsyncSession, group_id: int) -> GroupItem:
    g = (
        await session.execute(select(CommunityGroup).where(CommunityGroup.id == group_id))
    ).scalar_one_or_none()
    if g is None:
        raise AppException(ErrorCode.NOT_FOUND, "社群不存在")
    return _group_out(g)


async def join_group(session: AsyncSession, group_id: int) -> GroupJoinData:
    """加入社群：member_count 原子自增（无成员表，重复调用会重复计数【假设】）。"""
    row = await session.execute(
        update(CommunityGroup)
        .where(CommunityGroup.id == group_id)
        .values(member_count=CommunityGroup.member_count + 1)
        .returning(CommunityGroup.member_count)
    )
    count = row.scalar_one_or_none()
    if count is None:
        raise AppException(ErrorCode.NOT_FOUND, "社群不存在")
    await session.commit()
    return GroupJoinData(group_id=group_id, joined=True, member_count=int(count))


async def checkin_group(
    session: AsyncSession, user_id: int, group_id: int
) -> GroupCheckinData:
    """社群打卡：以 post_type=3 动态沉淀打卡内容（内容安全同动态口径）。"""
    g = (
        await session.execute(select(CommunityGroup).where(CommunityGroup.id == group_id))
    ).scalar_one_or_none()
    if g is None:
        raise AppException(ErrorCode.NOT_FOUND, "社群不存在")
    content = f"在「{g.name}」完成今日打卡"
    check = await sec.scan(content)
    post = CommunityPost(
        user_id=user_id,
        title=g.name,
        content=content,
        images=[],
        post_type=3,
        audit_status=1 if check.passed else 0,
    )
    session.add(post)
    await session.flush()
    if not check.passed:
        await _enqueue_review(
            session, target_type=1, target_id=post.id, user_id=user_id,
            snapshot=content, result=check.result, reason=check.reason,
        )
    days = await session.scalar(
        select(func.count()).select_from(CommunityPost).where(
            CommunityPost.user_id == user_id, CommunityPost.post_type == 3
        )
    )
    await session.commit()
    return GroupCheckinData(
        group_id=group_id, checked=True, checkin_days=int(days or 0), post_id=post.id
    )


# BE7b 约战


def _battle_item(b: Battle, joined: bool = False) -> BattleItem:
    return BattleItem(
        id=b.id,
        title=b.title or "",
        sport_name=b.sport_type,
        merchant_id=b.merchant_id,
        city=b.city,
        meet_at=b.meet_at or b.created_at,
        need_count=b.need_count,
        join_count=b.join_count,
        status=b.status,
        creator_id=b.creator_id,
        joined=joined,
    )


async def create_battle(session: AsyncSession, user_id: int, payload: BattleCreateIn) -> BattleItem:
    """发起约战（含 LBS city 与关联场馆券 merchant_id）；关联商家不存在 3001。

    发起人建战即占 1 位：join_count=1 且写入成员表一行（退出/防重复以此表为准）。
    """
    if payload.merchant_id is not None:
        merchant = await session.scalar(
            select(Merchant.id).where(Merchant.id == payload.merchant_id)
        )
        if merchant is None:
            raise AppException(ErrorCode.NOT_FOUND, "关联商家不存在")
    battle = Battle(
        title=payload.title,
        sport_type=payload.sport_name,
        merchant_id=payload.merchant_id,
        city=payload.city,
        meet_at=payload.meet_at,
        need_count=payload.need_count,
        join_count=1,  # 发起人本人已占 1 位
        creator_id=user_id,
        status=1,
    )
    session.add(battle)
    await session.flush()  # 先取 battle.id 再写成员行
    session.add(BattleParticipant(battle_id=battle.id, user_id=user_id))
    await session.commit()
    return _battle_item(battle, joined=True)


async def list_battles(
    session: AsyncSession,
    city: str | None,
    status: int | None,
    page: int,
    page_size: int,
    user_id: int | None = None,
) -> BattlePageData:
    conds = []
    if city:
        conds.append(Battle.city == city)
    if status is not None:
        conds.append(Battle.status == status)
    total = await session.scalar(select(func.count()).select_from(Battle).where(*conds))
    rows = (
        (
            await session.execute(
                select(Battle)
                .where(*conds)
                .order_by(Battle.created_at.desc(), Battle.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    # 当前用户的已加入集合：成员表命中 ∪ 本人发起（迁移兜底历史数据）
    joined_ids: set[int] = set()
    if user_id is not None and rows:
        ids = [b.id for b in rows]
        member_ids = set(
            await session.scalars(
                select(BattleParticipant.battle_id).where(
                    BattleParticipant.battle_id.in_(ids),
                    BattleParticipant.user_id == user_id,
                )
            )
        )
        joined_ids = member_ids | {b.id for b in rows if b.creator_id == user_id}
    return BattlePageData(
        items=[_battle_item(b, joined=b.id in joined_ids) for b in rows],
        page=PageMeta(page=page, page_size=page_size, total=int(total or 0)),
    )


async def join_battle(session: AsyncSession, battle_id: int, user_id: int) -> BattleJoinData:
    """加入约战：一人一位（成员表防重复）+ join_count 原子自增（并发不超员）。

    先 INSERT 成员行（唯一约束 battle_id+user_id 兜底并发重复），再原子自增
    join_count（WHERE status=1 AND join_count < need_count 保证不超员）。
    任一步失败即抛错且不 commit，本次写入整体回滚，不会出现「计了人数没进成员表」。
    """
    battle = await session.get(Battle, battle_id)
    if battle is None:
        raise AppException(ErrorCode.NOT_FOUND, "约战不存在")
    # 成员行占位：冲突（已加入）时不写入，据 returning 判定重复
    inserted = await session.execute(
        pg_insert(BattleParticipant)
        .values(battle_id=battle_id, user_id=user_id)
        .on_conflict_do_nothing(constraint="uq_battle_participant")
        .returning(BattleParticipant.id)
    )
    if inserted.first() is None or battle.creator_id == user_id:
        raise AppException(ErrorCode.VALIDATION_ERROR, "已加入该约战，不能重复加入")
    row = await session.execute(
        update(Battle)
        .where(
            Battle.id == battle_id,
            Battle.status == 1,
            Battle.join_count < Battle.need_count,
        )
        .values(join_count=Battle.join_count + 1)
        .returning(Battle.join_count, Battle.need_count)
    )
    updated = row.first()
    if updated is None:
        raise AppException(ErrorCode.VALIDATION_ERROR, "约战已满员或已结束")
    join_count, need_count = updated
    if join_count >= need_count:
        await session.execute(update(Battle).where(Battle.id == battle_id).values(status=2))
    await session.commit()
    return BattleJoinData(battle_id=battle_id, joined=True, join_count=int(join_count))


async def quit_battle(session: AsyncSession, battle_id: int, user_id: int) -> BattleQuitData:
    """退出约战：删成员行 + join_count 原子自减；满员(2)退出后回「招募中(1)」。

    仅招募中/满员（status 1/2）可退出；未加入返回 2001。
    """
    battle = await session.get(Battle, battle_id)
    if battle is None:
        raise AppException(ErrorCode.NOT_FOUND, "约战不存在")
    if battle.status not in (1, 2):
        raise AppException(ErrorCode.VALIDATION_ERROR, "约战已开始或已结束，无法退出")
    deleted = await session.execute(
        delete(BattleParticipant).where(
            BattleParticipant.battle_id == battle_id,
            BattleParticipant.user_id == user_id,
        )
    )
    if deleted.rowcount == 0:
        raise AppException(ErrorCode.VALIDATION_ERROR, "尚未加入该约战")
    row = await session.execute(
        update(Battle)
        .where(Battle.id == battle_id, Battle.join_count > 0)
        .values(
            join_count=Battle.join_count - 1,
            # 满员退出后恢复招募；进行中/结束不在此路径（上方已拦）
            status=1 if battle.status == 2 else battle.status,
        )
        .returning(Battle.join_count)
    )
    join_count = int(row.scalar_one())
    await session.commit()
    return BattleQuitData(battle_id=battle_id, joined=False, join_count=join_count)


# BE7b 挑战赛


def _challenge_item(c: Challenge, joined: bool) -> ChallengeItem:
    return ChallengeItem(
        id=c.id,
        title=c.title,
        start_at=c.start_at,
        end_at=c.end_at,
        badge_image=c.badge_image,
        join_count=c.join_count,
        status=c.status,
        joined=joined,
    )


async def _joined_challenge_ids(session: AsyncSession, user_id: int, ids: list[int]) -> set[int]:
    if not ids:
        return set()
    rows = await session.scalars(
        select(ChallengeJoin.challenge_id).where(
            ChallengeJoin.user_id == user_id, ChallengeJoin.challenge_id.in_(ids)
        )
    )
    return {i for i in rows.all() if i is not None}


async def list_challenges(
    session: AsyncSession, user_id: int, page: int, page_size: int
) -> ChallengePageData:
    total = await session.scalar(select(func.count()).select_from(Challenge))
    rows = (
        (
            await session.execute(
                select(Challenge)
                .order_by(Challenge.created_at.desc(), Challenge.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    joined = await _joined_challenge_ids(session, user_id, [c.id for c in rows])
    return ChallengePageData(
        items=[_challenge_item(c, c.id in joined) for c in rows],
        page=PageMeta(page=page, page_size=page_size, total=int(total or 0)),
    )


async def get_challenge(session: AsyncSession, user_id: int, challenge_id: int) -> ChallengeItem:
    c = (
        await session.execute(select(Challenge).where(Challenge.id == challenge_id))
    ).scalar_one_or_none()
    if c is None:
        raise AppException(ErrorCode.NOT_FOUND, "挑战赛不存在")
    joined = challenge_id in await _joined_challenge_ids(session, user_id, [challenge_id])
    return _challenge_item(c, joined)


async def join_challenge(
    session: AsyncSession, user_id: int, challenge_id: int
) -> ChallengeJoinData:
    """参加挑战赛：一人一赛一次（(challenge_id,user_id) 唯一）+ join_count 原子自增。"""
    c = (
        await session.execute(select(Challenge).where(Challenge.id == challenge_id))
    ).scalar_one_or_none()
    if c is None:
        raise AppException(ErrorCode.NOT_FOUND, "挑战赛不存在")
    if c.status == 2:
        raise AppException(ErrorCode.VALIDATION_ERROR, "挑战赛已结束")
    stmt = (
        pg_insert(ChallengeJoin)
        .values(challenge_id=challenge_id, user_id=user_id)
        .on_conflict_do_nothing(index_elements=["challenge_id", "user_id"])
        .returning(ChallengeJoin.id)
    )
    inserted = (await session.execute(stmt)).scalar_one_or_none()
    if inserted is None:
        raise AppException(ErrorCode.VALIDATION_ERROR, "你已参加该挑战赛")
    row = await session.execute(
        update(Challenge)
        .where(Challenge.id == challenge_id)
        .values(join_count=Challenge.join_count + 1)
        .returning(Challenge.join_count)
    )
    await session.commit()
    return ChallengeJoinData(
        challenge_id=challenge_id, joined=True, join_count=int(row.scalar_one())
    )


async def challenge_leaderboard(
    session: AsyncSession, challenge_id: int
) -> ChallengeLeaderboardData:
    """挑战赛排行榜：按 score 降序排名（score 空置后）；挑战赛不存在 3001。"""
    c = await session.scalar(select(Challenge.id).where(Challenge.id == challenge_id))
    if c is None:
        raise AppException(ErrorCode.NOT_FOUND, "挑战赛不存在")
    rows = (
        (
            await session.execute(
                select(ChallengeJoin)
                .where(ChallengeJoin.challenge_id == challenge_id)
                .order_by(ChallengeJoin.score.desc().nullslast(), ChallengeJoin.user_id.asc())
            )
        )
        .scalars()
        .all()
    )
    users = await _users_map(session, {r.user_id for r in rows})
    items = [
        LeaderboardEntry(rank=i + 1, user=_brief(users.get(r.user_id)), score=float(r.score or 0))
        for i, r in enumerate(rows)
    ]
    return ChallengeLeaderboardData(challenge_id=challenge_id, items=items)


# BE7b 热量控制榜


def _period_range(period_type: int, period_key: str) -> tuple[date, date]:
    """period_key → [start, end]：1日 YYYY-MM-DD / 2周 YYYY-Www / 3月 YYYY-MM。非法 key 2001。"""
    try:
        if period_type == 1:
            d = datetime.strptime(period_key, "%Y-%m-%d").date()
            return d, d
        if period_type == 2:
            start = datetime.strptime(f"{period_key}-1", "%G-W%V-%u").date()
            return start, start + timedelta(days=6)
        if period_type == 3:
            start = datetime.strptime(period_key, "%Y-%m").date()
            next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
            return start, next_month - timedelta(days=1)
    except ValueError as exc:
        raise AppException(
            ErrorCode.VALIDATION_ERROR, "period_key 与 period_type 不匹配"
        ) from exc
    raise AppException(ErrorCode.VALIDATION_ERROR, "period_type 非法")


def default_period_key(period_type: int, today: date | None = None) -> str:
    d = today or datetime.now(_TZ).date()
    if period_type == 1:
        return d.isoformat()
    if period_type == 2:
        year, week, _ = d.isocalendar()
        return f"{year}-W{week:02d}"
    return f"{d.year}-{d.month:02d}"


async def get_leaderboard(
    session: AsyncSession, period_type: int, period_key: str | None
) -> LeaderboardData:
    """热量控制榜：按期从 daily_snapshot 现算得分（-Σ缺口）并 upsert 预聚合表后返回。"""
    key = period_key or default_period_key(period_type)
    start, end = _period_range(period_type, key)
    rows = (
        await session.execute(
            select(DailySnapshot.user_id, func.sum(DailySnapshot.deficit))
            .where(
                DailySnapshot.snapshot_date >= start,
                DailySnapshot.snapshot_date <= end,
                DailySnapshot.user_id.isnot(None),
            )
            .group_by(DailySnapshot.user_id)
        )
    ).all()
    # score = -Σdeficit（缺口为负 → 得分正，缺口越大分越高）
    scored = sorted(
        ((uid, round(-float(total or 0), 1)) for uid, total in rows),
        key=lambda x: (-x[1], x[0]),
    )
    users = await _users_map(session, {uid for uid, _ in scored})
    items: list[LeaderboardEntry] = []
    for i, (uid, score) in enumerate(scored):
        rank = i + 1
        items.append(LeaderboardEntry(rank=rank, user=_brief(users.get(uid)), score=score))
        await session.execute(
            pg_insert(Leaderboard)
            .values(period_type=period_type, period_key=key, user_id=uid, score=score, rank=rank)
            .on_conflict_do_update(
                index_elements=["period_type", "period_key", "user_id"],
                set_={"score": score, "rank": rank},
            )
        )
    await session.commit()
    return LeaderboardData(period_type=period_type, period_key=key, items=items)
