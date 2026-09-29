"""Phase 4 内容安全测试（BE7c + ADM）：违规词/违规图拦截入审核队列、正常放行、正文入库存原文。

无微信 Key 环境下内容安全走本地 mock 降级（app/services/content_security.py）。
XSS 防护交由渲染层：正文入库不转义，前端模板插值自动转义（断言全仓页面无 v-html/innerHTML）。
"""

from pathlib import Path

from sqlalchemy import func, select

from app.models import CommunityComment, CommunityPost, Review


async def _pending_reviews(db_session) -> list[Review]:
    return (
        (await db_session.execute(select(Review).order_by(Review.id))).scalars().all()
    )


async def test_violation_word_post_queued_not_listed(db_client, db_session, authed):
    r = await db_client.post(
        "/api/community/post", headers=authed["headers"], json={"content": "这是违规词内容"}
    )
    assert r.json()["code"] == 0
    assert r.json()["data"]["audit_status"] == 0  # 待审
    # 不直接展示
    lst = await db_client.get("/api/community/post/list", headers=authed["headers"])
    assert lst.json()["data"]["items"] == []
    # 进审核队列
    reviews = await _pending_reviews(db_session)
    assert len(reviews) == 1
    assert reviews[0].target_type == 1 and reviews[0].status == 0
    assert reviews[0].target_id == r.json()["data"]["id"]


async def test_violation_image_post_queued(db_client, db_session, authed):
    r = await db_client.post(
        "/api/community/post",
        headers=authed["headers"],
        json={"content": "看图", "images": ["https://cos.example.com/violation.png"]},
    )
    assert r.json()["data"]["audit_status"] == 0
    assert len(await _pending_reviews(db_session)) == 1


async def test_normal_content_passes(db_client, db_session, authed):
    r = await db_client.post(
        "/api/community/post", headers=authed["headers"], json={"content": "今天吃得健康"}
    )
    assert r.json()["data"]["audit_status"] == 1
    assert len(await _pending_reviews(db_session)) == 0


async def test_post_content_stored_raw_roundtrip(db_client, authed):
    """入库存原文（写库前不转义），避免前端 {{ }} 二次转义后用户看到 HTML 实体。"""
    raw = 'A&B<z>"\'&amp;'
    pid = (
        await db_client.post(
            "/api/community/post", headers=authed["headers"], json={"content": raw}
        )
    ).json()["data"]["id"]
    detail = (
        await db_client.get(f"/api/community/post/{pid}", headers=authed["headers"])
    ).json()["data"]
    assert detail["content"] == raw


def test_pages_do_not_use_v_html():
    """XSS 防护依赖渲染层插值自动转义：全仓页面模板不得用 v-html / innerHTML 绕过。"""
    root = Path(__file__).resolve().parents[2]
    offenders = []
    for base in ("miniapp/src", "admin/src"):
        for page in (root / base).rglob("*.vue"):
            text = page.read_text(encoding="utf-8")
            if "v-html" in text or "innerHTML" in text:
                offenders.append(str(page.relative_to(root)))
    assert offenders == []


async def test_violation_comment_queued_not_listed(db_client, db_session, authed):
    pid = (
        await db_client.post(
            "/api/community/post", headers=authed["headers"], json={"content": "正常动态"}
        )
    ).json()["data"]["id"]
    r = await db_client.post(
        f"/api/community/post/{pid}/comment",
        headers=authed["headers"],
        json={"content": "评论含违规词"},
    )
    assert r.json()["code"] == 0
    comments = (
        await db_client.get(f"/api/community/post/{pid}/comment/list", headers=authed["headers"])
    ).json()["data"]["items"]
    assert comments == []
    reviews = await _pending_reviews(db_session)
    assert len(reviews) == 1 and reviews[0].target_type == 2
    # 违规评论不计数
    posted = await db_session.scalar(
        select(CommunityPost.comment_count).where(CommunityPost.id == pid)
    )
    assert posted == 0
    assert await db_session.scalar(select(func.count()).select_from(CommunityComment)) == 1


async def test_admin_review_approve_makes_post_visible(db_client, db_session, admin_authed, authed):
    post_id = (
        await db_client.post(
            "/api/community/post", headers=authed["headers"], json={"content": "含违规词待审"}
        )
    ).json()["data"]["id"]
    # 管理端登录
    login = await db_client.post("/api/admin/login", json=admin_authed)
    token = login.json()["data"]["token"]
    admin_h = {"Authorization": f"Bearer {token}"}

    queue = (await db_client.get("/api/admin/audit/list?status=0", headers=admin_h)).json()["data"][
        "items"
    ]
    assert [i["id"] for i in queue] and queue[0]["target_id"] == post_id

    review_id = queue[0]["id"]
    reviewed = (
        await db_client.post(
            f"/api/admin/audit/{review_id}/review", headers=admin_h, json={"status": 1}
        )
    ).json()["data"]
    assert reviewed["status"] == 1
    # 通过后内容对外可见
    lst = await db_client.get("/api/community/post/list", headers=authed["headers"])
    assert post_id in [p["id"] for p in lst.json()["data"]["items"]]


async def test_admin_review_reject_hides_post(db_client, db_session, admin_authed, authed):
    post_id = (
        await db_client.post(
            "/api/community/post", headers=authed["headers"], json={"content": "违规词内容"}
        )
    ).json()["data"]["id"]
    login = await db_client.post("/api/admin/login", json=admin_authed)
    admin_h = {"Authorization": f"Bearer {login.json()['data']['token']}"}
    queue = (await db_client.get("/api/admin/audit/list?status=0", headers=admin_h)).json()["data"][
        "items"
    ]
    review_id = queue[0]["id"]
    reviewed = (
        await db_client.post(
            f"/api/admin/audit/{review_id}/review",
            headers=admin_h,
            json={"status": 2, "reason": "内容不合规"},
        )
    ).json()["data"]
    assert reviewed["status"] == 2 and reviewed["reject_reason"] == "内容不合规"
    audit_status = await db_session.scalar(
        select(CommunityPost.audit_status).where(CommunityPost.id == post_id)
    )
    assert audit_status == 2
    lst = await db_client.get("/api/community/post/list", headers=authed["headers"])
    assert lst.json()["data"]["items"] == []


async def test_comment_review_approve_syncs_count_idempotent(
    db_client, db_session, admin_authed, authed
):
    """评论审核通过：动态 comment_count 重算为可见评论数（口径与列表一致）；重复审核不重复累加。"""
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
    login = await db_client.post("/api/admin/login", json=admin_authed)
    admin_h = {"Authorization": f"Bearer {login.json()['data']['token']}"}
    queue = (await db_client.get("/api/admin/audit/list?status=0", headers=admin_h)).json()["data"][
        "items"
    ]
    assert queue[0]["target_type"] == 2
    review_id = queue[0]["id"]

    await db_client.post(
        f"/api/admin/audit/{review_id}/review", headers=admin_h, json={"status": 1}
    )
    comments = (
        await db_client.get(f"/api/community/post/{pid}/comment/list", headers=authed["headers"])
    ).json()["data"]["items"]
    assert len(comments) == 1  # 审核通过后对外可见
    count = await db_session.scalar(
        select(CommunityPost.comment_count).where(CommunityPost.id == pid)
    )
    assert count == 1

    # 重复审核通过：幂等，不重复累加
    await db_client.post(
        f"/api/admin/audit/{review_id}/review", headers=admin_h, json={"status": 1}
    )
    count_again = await db_session.scalar(
        select(CommunityPost.comment_count).where(CommunityPost.id == pid)
    )
    assert count_again == 1
