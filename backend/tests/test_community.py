"""Phase 4 社区与社交测试（BE7a/BE7b/BE7c）：动态/评论/点赞/监督/社群/约战/挑战赛/榜单/周点评。

均走真实 PostgreSQL（db_client + db_session）。一个行为一个测试，同类边界用 parametrize 合并。
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.core.security import create_access_token
from app.models import (
    BodyProfile,
    Challenge,
    ChallengeJoin,
    CommunityGroup,
    CommunityPost,
    DailySnapshot,
    Food,
    Supervise,
    User,
)

TZ = timezone(timedelta(hours=8))


# ---------------------------------------------------------------------------
# 造数助手
# ---------------------------------------------------------------------------


async def _other_actor(db_session, openid: str = "community-other") -> dict:
    """另造一个登录用户，返回 {user_id, headers}。"""
    user = User(openid=openid, nickname="搭子B", gender=1)
    db_session.add(user)
    await db_session.flush()
    token = create_access_token(str(user.id), openid=user.openid)
    await db_session.commit()
    return {"user_id": user.id, "headers": {"Authorization": f"Bearer {token}"}}


async def _create_challenge(db_session, title: str = "21天挑战赛") -> Challenge:
    c = Challenge(title=title, join_count=0, status=1)
    db_session.add(c)
    await db_session.commit()
    return c


async def _create_group(db_session, name: str = "减脂餐交流社"):
    g = CommunityGroup(name=name, category="减脂", member_count=0, city="上海")
    db_session.add(g)
    await db_session.commit()
    return g


def _today() -> str:
    return datetime.now(TZ).date().isoformat()


# ---------------------------------------------------------------------------
# BE7a 动态
# ---------------------------------------------------------------------------


async def test_create_post_visible_in_list(db_client, db_session, authed):
    r = await db_client.post(
        "/api/community/post", headers=authed["headers"], json={"content": "今天午餐打卡清蒸鱼"}
    )
    assert r.json()["code"] == 0
    assert r.json()["data"]["audit_status"] == 1
    post_id = r.json()["data"]["id"]

    lst = await db_client.get("/api/community/post/list", headers=authed["headers"])
    items = lst.json()["data"]["items"]
    assert [p["id"] for p in items] == [post_id]
    assert items[0]["content"] == "今天午餐打卡清蒸鱼"


async def test_anonymous_post_hides_author(db_client, authed):
    await db_client.post(
        "/api/community/post",
        headers=authed["headers"],
        json={"content": "匿名吐槽", "anonymous": True},
    )
    lst = await db_client.get("/api/community/post/list", headers=authed["headers"])
    item = lst.json()["data"]["items"][0]
    assert item["anonymous"] is True
    assert item["user"]["nickname"] == "匿名减友"


async def test_like_is_unique_per_user(db_client, authed):
    pid = (
        await db_client.post(
            "/api/community/post", headers=authed["headers"], json={"content": "打卡"}
        )
    ).json()["data"]["id"]
    like_url = f"/api/community/post/{pid}/like"
    first = (await db_client.post(like_url, headers=authed["headers"])).json()
    second = (await db_client.post(like_url, headers=authed["headers"])).json()
    assert first["data"]["like_count"] == 1
    assert second["data"]["like_count"] == 1  # 一人一赞：重复点赞不累加

    unlike = (await db_client.delete(like_url, headers=authed["headers"])).json()
    assert unlike["data"]["liked"] is False
    assert unlike["data"]["like_count"] == 0


async def test_create_comment_and_count(db_client, authed):
    pid = (
        await db_client.post(
            "/api/community/post", headers=authed["headers"], json={"content": "打卡"}
        )
    ).json()["data"]["id"]
    r = await db_client.post(
        f"/api/community/post/{pid}/comment", headers=authed["headers"], json={"content": "加油！"}
    )
    assert r.json()["code"] == 0

    comments = (
        await db_client.get(f"/api/community/post/{pid}/comment/list", headers=authed["headers"])
    ).json()["data"]["items"]
    assert [c["content"] for c in comments] == ["加油！"]
    detail = (
        await db_client.get(f"/api/community/post/{pid}", headers=authed["headers"])
    ).json()["data"]
    assert detail["comment_count"] == 1


# ---------------------------------------------------------------------------
# 评论审核计数口径（BE9 审核回写 comment_count）
# ---------------------------------------------------------------------------


async def _admin_headers(db_client, admin_authed) -> dict:
    login = await db_client.post("/api/admin/login", json=admin_authed)
    return {"Authorization": f"Bearer {login.json()['data']['token']}"}


async def _flagged_comment_review(db_client, admin_h, authed) -> tuple[int, int]:
    """建动态 + 违规评论入审 → 返回 (post_id, review_id)。"""
    pid = (
        await db_client.post(
            "/api/community/post", headers=authed["headers"], json={"content": "正常动态"}
        )
    ).json()["data"]["id"]
    await db_client.post(
        f"/api/community/post/{pid}/comment",
        headers=authed["headers"],
        json={"content": "评论含违规词"},
    )
    queue = (
        await db_client.get("/api/admin/audit/list?status=0", headers=admin_h)
    ).json()["data"]["items"]
    assert len(queue) == 1 and queue[0]["target_type"] == 2
    return pid, queue[0]["id"]


async def _comment_count(db_session, pid: int) -> int:
    return await db_session.scalar(
        select(CommunityPost.comment_count).where(CommunityPost.id == pid)
    )


async def test_comment_review_approve_then_reject_then_approve_no_drift(
    db_client, db_session, admin_authed, authed
):
    """通过→驳回→再通过：comment_count 与可见评论数收敛为 1（不漂移）。"""
    admin_h = await _admin_headers(db_client, admin_authed)
    pid, review_id = await _flagged_comment_review(db_client, admin_h, authed)
    url = f"/api/admin/audit/{review_id}/review"

    await db_client.post(url, headers=admin_h, json={"status": 1})
    await db_client.post(url, headers=admin_h, json={"status": 2, "reason": "驳回"})
    await db_client.post(url, headers=admin_h, json={"status": 1})

    comments = (
        await db_client.get(f"/api/community/post/{pid}/comment/list", headers=authed["headers"])
    ).json()["data"]["items"]
    assert len(comments) == 1
    assert await _comment_count(db_session, pid) == 1


async def test_comment_review_reject_only_keeps_count_zero(
    db_client, db_session, admin_authed, authed
):
    """仅驳回（从未可见）：comment_count 保持 0。"""
    admin_h = await _admin_headers(db_client, admin_authed)
    pid, review_id = await _flagged_comment_review(db_client, admin_h, authed)
    await db_client.post(
        f"/api/admin/audit/{review_id}/review",
        headers=admin_h,
        json={"status": 2, "reason": "驳回"},
    )
    comments = (
        await db_client.get(f"/api/community/post/{pid}/comment/list", headers=authed["headers"])
    ).json()["data"]["items"]
    assert comments == []
    assert await _comment_count(db_session, pid) == 0


async def test_delete_post_owner_ok(db_client, authed):
    pid = (
        await db_client.post(
            "/api/community/post", headers=authed["headers"], json={"content": "待删"}
        )
    ).json()["data"]["id"]
    r = await db_client.delete(f"/api/community/post/{pid}", headers=authed["headers"])
    assert r.json()["data"]["deleted"] is True
    lst = await db_client.get("/api/community/post/list", headers=authed["headers"])
    assert lst.json()["data"]["items"] == []


async def test_delete_post_non_owner_forbidden(db_client, db_session, authed):
    pid = (
        await db_client.post(
            "/api/community/post", headers=authed["headers"], json={"content": "别人的"}
        )
    ).json()["data"]["id"]
    other = await _other_actor(db_session)
    r = await db_client.delete(f"/api/community/post/{pid}", headers=other["headers"])
    assert r.status_code == 403
    assert r.json()["code"] == 1002


# ---------------------------------------------------------------------------
# BE7b 监督搭子
# ---------------------------------------------------------------------------


async def test_supervise_match_and_one_pair_unique(db_client, db_session, authed):
    other = await _other_actor(db_session, "sup-b")
    r = await db_client.post(
        "/api/community/supervise/match",
        headers=authed["headers"],
        json={"partner_id": other["user_id"]},
    )
    assert r.json()["code"] == 0
    assert r.json()["data"]["partner"]["id"] == other["user_id"]
    assert (
        await db_session.scalar(
            select(Supervise.id).where(Supervise.user_a == authed["user_id"])
        )
        is not None
        or await db_session.scalar(
            select(Supervise.id).where(Supervise.user_b == authed["user_id"])
        )
        is not None
    )
    # 一人一对唯一：已有生效关系再次匹配 → 2001
    again = await db_client.post(
        "/api/community/supervise/match", headers=authed["headers"], json={}
    )
    assert again.status_code == 422
    assert again.json()["code"] == 2001


async def test_supervise_match_self_rejected(db_client, authed):
    r = await db_client.post(
        "/api/community/supervise/match",
        headers=authed["headers"],
        json={"partner_id": authed["user_id"]},
    )
    assert r.status_code == 422
    assert r.json()["code"] == 2001


async def test_supervise_remind_and_records(db_client, db_session, authed):
    other = await _other_actor(db_session, "sup-c")
    sup_id = (
        await db_client.post(
            "/api/community/supervise/match",
            headers=authed["headers"],
            json={"partner_id": other["user_id"]},
        )
    ).json()["data"]["id"]
    remind = (
        await db_client.post(f"/api/community/supervise/{sup_id}/remind", headers=authed["headers"])
    ).json()
    assert remind["data"]["reminded"] is True

    db_session.add(
        DailySnapshot(
            user_id=other["user_id"], snapshot_date=datetime.now(TZ).date(), intake=1500,
            deficit=-500, steps=8000,
        )
    )
    await db_session.commit()
    recs = (
        await db_client.get(f"/api/community/supervise/{sup_id}/records", headers=authed["headers"])
    ).json()["data"]
    assert recs["partner"]["id"] == other["user_id"]
    assert recs["items"][0]["deficit"] == -500


# ---------------------------------------------------------------------------
# BE7b 兴趣社群
# ---------------------------------------------------------------------------


async def test_group_join_increments_member_count(db_client, db_session, authed):
    g = await _create_group(db_session, "join-社群")
    r = await db_client.post(f"/api/community/group/{g.id}/join", headers=authed["headers"])
    assert r.json()["code"] == 0
    assert r.json()["data"]["member_count"] == 1


async def test_group_checkin_creates_post(db_client, db_session, authed):
    g = await _create_group(db_session, "checkin-社群")
    r = await db_client.post(f"/api/community/group/{g.id}/checkin", headers=authed["headers"])
    assert r.json()["code"] == 0
    assert r.json()["data"]["post_id"]
    lst = await db_client.get(
        "/api/community/post/list?post_type=3", headers=authed["headers"]
    )
    assert r.json()["data"]["post_id"] in [p["id"] for p in lst.json()["data"]["items"]]


# ---------------------------------------------------------------------------
# BE7b 约战
# ---------------------------------------------------------------------------


async def _create_battle(db_client, authed, need_count: int = 2) -> int:
    meet = (datetime.now(TZ) + timedelta(days=2)).isoformat()
    r = await db_client.post(
        "/api/community/battle",
        headers=authed["headers"],
        json={"title": "轻食约战", "sport_name": "轻食", "city": "上海", "meet_at": meet,
              "need_count": need_count},
    )
    assert r.json()["code"] == 0
    return r.json()["data"]["id"]


async def test_battle_create_and_join_until_full(db_client, authed):
    bid = await _create_battle(db_client, authed, need_count=2)
    first = await db_client.post(
        "/api/community/battle/join", headers=authed["headers"], json={"battle_id": bid}
    )
    assert first.json()["data"]["join_count"] == 2  # 发起人占 1 位，加入后满员
    full = await db_client.post(
        "/api/community/battle/join", headers=authed["headers"], json={"battle_id": bid}
    )
    assert full.status_code == 422
    assert full.json()["code"] == 2001


async def test_battle_join_concurrent_no_overflow(db_client, authed):
    import asyncio

    bid = await _create_battle(db_client, authed, need_count=3)  # join_count 初始 1

    async def _join():
        return (
            await db_client.post(
                "/api/community/battle/join",
                headers=authed["headers"],
                json={"battle_id": bid},
            )
        ).json()

    results = await asyncio.gather(*[_join() for _ in range(5)])
    ok = [r for r in results if r["code"] == 0]
    assert len(ok) == 2  # 仅剩 2 位，原子自增不超员


# ---------------------------------------------------------------------------
# BE7b 挑战赛
# ---------------------------------------------------------------------------


async def test_challenge_join_once(db_client, db_session, authed):
    c = await _create_challenge(db_session, "join-挑战赛")
    first = await db_client.post(f"/api/community/challenge/{c.id}/join", headers=authed["headers"])
    assert first.json()["data"]["joined"] is True
    assert first.json()["data"]["join_count"] == 1
    dup = await db_client.post(f"/api/community/challenge/{c.id}/join", headers=authed["headers"])
    assert dup.status_code == 422
    assert dup.json()["code"] == 2001


async def test_challenge_leaderboard_ranks(db_client, db_session, authed):
    c = await _create_challenge(db_session, "榜-挑战赛")
    other = await _other_actor(db_session, "chal-b")
    db_session.add_all(
        [
            ChallengeJoin(challenge_id=c.id, user_id=authed["user_id"], score=80),
            ChallengeJoin(challenge_id=c.id, user_id=other["user_id"], score=95),
        ]
    )
    await db_session.commit()
    r = await db_client.get(
        f"/api/community/challenge/{c.id}/leaderboard", headers=authed["headers"]
    )
    items = r.json()["data"]["items"]
    assert [i["rank"] for i in items] == [1, 2]
    assert items[0]["user"]["id"] == other["user_id"] and items[0]["score"] == 95


# ---------------------------------------------------------------------------
# BE7b 热量控制榜
# ---------------------------------------------------------------------------


async def test_leaderboard_ranked_from_snapshots(db_client, db_session, authed):
    other = await _other_actor(db_session, "lb-b")
    day = datetime.now(TZ).date()
    db_session.add_all(
        [
            DailySnapshot(user_id=authed["user_id"], snapshot_date=day, deficit=-300),
            DailySnapshot(user_id=other["user_id"], snapshot_date=day, deficit=-800),
        ]
    )
    await db_session.commit()
    r = await db_client.get(
        f"/api/community/leaderboard?period_type=1&period_key={_today()}",
        headers=authed["headers"],
    )
    items = r.json()["data"]["items"]
    # score = -Σdeficit：缺口更大者排名更高
    assert items[0]["user"]["id"] == other["user_id"] and items[0]["score"] == 800.0


# ---------------------------------------------------------------------------
# 同款减友经验
# ---------------------------------------------------------------------------


async def test_experience_list_only_post_type_2(db_client, authed):
    await db_client.post(
        "/api/community/post",
        headers=authed["headers"],
        json={"content": "我的减脂经验", "post_type": 2, "title": "经验贴"},
    )
    await db_client.post(
        "/api/community/post", headers=authed["headers"], json={"content": "普通动态"}
    )
    r = await db_client.get("/api/community/experience/list", headers=authed["headers"])
    items = r.json()["data"]["items"]
    assert [i["content"] for i in items] == ["我的减脂经验"]


# ---------------------------------------------------------------------------
# BE7c AI 周点评
# ---------------------------------------------------------------------------


async def test_weekly_comment_template(db_client, db_session, authed):
    day = datetime.now(TZ).date()
    db_session.add(
        DailySnapshot(
            user_id=authed["user_id"], snapshot_date=day, intake=1500, deficit=-400, steps=9000
        )
    )
    await db_session.commit()
    r = await db_client.post("/api/ai/weekly-comment", headers=authed["headers"], json={})
    data = r.json()["data"]
    assert r.json()["code"] == 0
    assert "免责" in data["content"] or "仅供参考" in data["content"]
    assert data["highlights"]
    assert len(data["week"]) == 8  # YYYY-Www


# ---------------------------------------------------------------------------
# 邀请（真实现）
# ---------------------------------------------------------------------------


async def test_invite_bind_and_progress(db_client, db_session, authed):
    """邀请裂变（新口径）：绑定成功即有效（注册即有效）并实时计数（变更记录 2026-10-01）。"""
    code = (await db_client.post("/api/invite", headers=authed["headers"], json={})).json()["data"][
        "invite_code"
    ]
    other = await _other_actor(db_session, "inv-b")
    bound = await db_client.post(
        "/api/invite", headers=other["headers"], json={"invite_code": code}
    )
    assert bound.json()["data"]["bound"] is True
    progress = (
        await db_client.get("/api/invite/progress", headers=authed["headers"])
    ).json()["data"]
    assert progress["invitee_count"] == 1  # 注册即有效，绑定即计数
    assert progress["next_tier"]["need"] == 2  # 下一档 3 人
    assert progress["next_tier"]["reward"] == "高级版40次/日"


async def test_battle_join_missing_returns_404(db_client, authed):
    r = await db_client.post(
        "/api/community/battle/join", headers=authed["headers"], json={"battle_id": 999999}
    )
    assert r.status_code == 404
    assert r.json()["code"] == 3001


# ---------------------------------------------------------------------------
# 修复回归：非法参数 / 不存在资源 / 并发
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("period_type", "period_key"),
    [(1, "abc"), (2, "2026-W99"), (3, "2026-13")],
)
async def test_leaderboard_invalid_period_key_returns_2001(
    db_client, authed, period_type, period_key
):
    r = await db_client.get(
        f"/api/community/leaderboard?period_type={period_type}&period_key={period_key}",
        headers=authed["headers"],
    )
    assert r.status_code == 422
    assert r.json()["code"] == 2001


async def test_invite_bind_unknown_inviter_returns_404(db_client, authed):
    r = await db_client.post(
        "/api/invite", headers=authed["headers"], json={"invite_code": "INV-999999"}
    )
    assert r.status_code == 404
    assert r.json()["code"] == 3001


async def test_battle_create_unknown_merchant_returns_404(db_client, authed):
    meet = (datetime.now(TZ) + timedelta(days=1)).isoformat()
    r = await db_client.post(
        "/api/community/battle",
        headers=authed["headers"],
        json={"title": "约战", "meet_at": meet, "merchant_id": 999999},
    )
    assert r.status_code == 404
    assert r.json()["code"] == 3001


async def test_challenge_leaderboard_missing_returns_404(db_client, authed):
    r = await db_client.get(
        "/api/community/challenge/999999/leaderboard", headers=authed["headers"]
    )
    assert r.status_code == 404
    assert r.json()["code"] == 3001


async def test_supervise_match_concurrent_single_relation(db_client, db_session, authed):
    import asyncio

    b = await _other_actor(db_session, "sup-race-b")
    c = await _other_actor(db_session, "sup-race-c")

    async def _match(partner_id: int) -> dict:
        return (
            await db_client.post(
                "/api/community/supervise/match",
                headers=authed["headers"],
                json={"partner_id": partner_id},
            )
        ).json()

    results = await asyncio.gather(_match(b["user_id"]), _match(c["user_id"]))
    assert len([r for r in results if r["code"] == 0]) == 1
    assert len([r for r in results if r["code"] == 2001]) == 1
    # 同一用户仅 1 条生效关系
    active = await db_session.scalar(
        select(func.count())
        .select_from(Supervise)
        .where(
            Supervise.status == 1,
            (Supervise.user_a == authed["user_id"]) | (Supervise.user_b == authed["user_id"]),
        )
    )
    assert active == 1
