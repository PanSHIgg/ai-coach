"""F6 安全测试：写接口幂等 / 防重放。

Phase 5 前：写接口无幂等键，1 秒内重复提交会全部落库（缺口）。
Phase 5 已修：写接口（POST/PUT/PATCH/DELETE，`/api` 前缀）携带 `Idempotency-Key` 请求头时，
同一 key 在 TTL 窗口内**仅首次放行**，其余返回 HTTP 409 + 业务码 4002
（见 app/core/idempotency.py）；**不带该头的请求行为完全不变**。

本文件覆盖（同类行为用 parametrize 合并，一个行为一个用例）：
- 同一 key 重放 10 次 → 仅首次成功（下单 / 发帖各一次）；
- 首次请求失败（4xx/5xx）→ 释放 key，同 key 重试可再次进入业务逻辑（P2-10）；
- 不带 Idempotency-Key → 不拦截（旧客户端零影响）；
- 不同 key 的同内容请求 → 各自成功（避免误拦不同逻辑操作）；
- 身份隔离：A 的 key 被 B 使用时互不影响（去重键含 Authorization 指纹）。

另保留：登录重复提交（openid 幂等）与支付状态机防重复推进（2001）。
核销码重复核销（5004）已由 tests/test_orders.py 覆盖，此处不重复。
"""

from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.core.security import create_access_token
from app.models import (
    CommunityPost,
    Merchant,
    MerchantSku,
    Order,
    SkuCatalog,
    User,
    UserBenefit,
)
from app.schemas.common import ErrorCode

REPLAY_TIMES = 10


async def _seed_merchant_sku(db_session, code="FD-001", price=25.0, stock=-1):
    merchant = Merchant(name="重放测试店", category="轻食", status=1, audit_status=1)
    db_session.add(merchant)
    await db_session.flush()
    catalog_id = (
        await db_session.execute(select(SkuCatalog.id).where(SkuCatalog.code == code))
    ).scalar_one()
    sku = MerchantSku(
        merchant_id=merchant.id, catalog_id=catalog_id, price=price, stock=stock, status=1
    )
    db_session.add(sku)
    await db_session.commit()
    return merchant, sku


async def _make_user(db_session, suffix: str) -> dict:
    """预置一个独立用户并签发 token（供身份隔离用例构造第二个身份）。"""
    user = User(openid=f"replay-{suffix}-{uuid4().hex}", nickname="隔离用户", gender=1)
    db_session.add(user)
    await db_session.flush()
    db_session.add(UserBenefit(user_id=user.id, tier=0, ai_times_left=10))
    await db_session.commit()
    token = create_access_token(str(user.id), openid=user.openid)
    return {"user_id": user.id, "headers": {"Authorization": f"Bearer {token}"}}


async def _post_repeated(client, headers, path, body, times=REPLAY_TIMES) -> list:
    """串行重复提交 times 次，返回响应对象列表。"""
    return [await client.post(path, headers=headers, json=body) for _ in range(times)]


@pytest.mark.parametrize("target", ["order", "community_post"])
async def test_same_idempotency_key_replay_only_first_wins(
    db_client, db_session, authed, target
):
    """携带同一 Idempotency-Key 重放 10 次：仅首次成功，第 2..10 次 409 + 4002。"""
    if target == "order":
        merchant, sku = await _seed_merchant_sku(db_session)
        path = "/api/order"
        body = {"merchant_id": merchant.id, "items": [{"sku_id": sku.id, "qty": 1}]}
        count_model = Order
    else:
        path = "/api/community/post"
        body = {"content": "重放测试动态"}
        count_model = CommunityPost

    headers = {**authed["headers"], "Idempotency-Key": f"replay-{target}-{uuid4().hex}"}
    responses = await _post_repeated(db_client, headers, path, body, REPLAY_TIMES)

    first, *replays = responses
    assert (first.status_code, first.json()["code"]) == (200, ErrorCode.OK), first.text
    for resp in replays:
        assert resp.status_code == 409, (target, resp.status_code, resp.text)
        assert resp.json()["code"] == ErrorCode.DUPLICATE_REQUEST, resp.text
        assert resp.json()["idempotency_replayed"] is True, resp.text

    created = await db_session.scalar(select(func.count()).select_from(count_model))
    assert created == 1, f"{target} 落库条数={created}（期望 1，重放未被拦截）"


async def test_without_idempotency_key_not_intercepted(db_client, db_session, authed):
    """旧客户端零影响：不带 Idempotency-Key 的写请求不被幂等中间件拦截，10 次全部落库。"""
    merchant, sku = await _seed_merchant_sku(db_session)
    body = {"merchant_id": merchant.id, "items": [{"sku_id": sku.id, "qty": 1}]}
    responses = await _post_repeated(db_client, authed["headers"], "/api/order", body)

    assert all(
        (resp.status_code, resp.json()["code"]) == (200, ErrorCode.OK) for resp in responses
    ), [resp.text for resp in responses]
    created = await db_session.scalar(select(func.count()).select_from(Order))
    assert created == REPLAY_TIMES, f"落库订单数={created}（期望 {REPLAY_TIMES}）"


async def test_different_idempotency_keys_all_succeed(db_client, db_session, authed):
    """不同 Idempotency-Key 的同内容请求各自成功（避免误拦不同逻辑操作）。"""
    body = {"content": "不同键同内容"}
    for _ in range(3):
        headers = {**authed["headers"], "Idempotency-Key": f"distinct-{uuid4().hex}"}
        resp = await db_client.post("/api/community/post", headers=headers, json=body)
        assert (resp.status_code, resp.json()["code"]) == (200, ErrorCode.OK), resp.text

    created = await db_session.scalar(select(func.count()).select_from(CommunityPost))
    assert created == 3, f"落库动态条数={created}（期望 3）"


async def test_idempotency_key_isolated_per_identity(db_client, db_session, authed):
    """身份隔离：A 的 Idempotency-Key 被 B 持有时互不影响（去重键含身份指纹）。"""
    other = await _make_user(db_session, "other")
    key = f"shared-{uuid4().hex}"
    body = {"content": "身份隔离动态"}

    a_headers = {**authed["headers"], "Idempotency-Key": key}
    first_a = await db_client.post("/api/community/post", headers=a_headers, json=body)
    assert (first_a.status_code, first_a.json()["code"]) == (200, ErrorCode.OK), first_a.text
    # A 自己重放同 key → 拦截
    replay_a = await db_client.post("/api/community/post", headers=a_headers, json=body)
    assert (replay_a.status_code, replay_a.json()["code"]) == (
        409,
        ErrorCode.DUPLICATE_REQUEST,
    ), replay_a.text

    # B 用同一 key（不同 Authorization 指纹）→ 不受 A 影响，正常放行
    b_headers = {**other["headers"], "Idempotency-Key": key}
    first_b = await db_client.post("/api/community/post", headers=b_headers, json=body)
    assert (first_b.status_code, first_b.json()["code"]) == (200, ErrorCode.OK), first_b.text

    created = await db_session.scalar(select(func.count()).select_from(CommunityPost))
    assert created == 2, f"落库动态条数={created}（期望 2）"


async def test_failed_first_request_releases_key_for_retry(db_client, authed):
    """首次请求以 4xx 结束（空 events → 422/2001）时释放 key：同 key 重试可再次进入业务逻辑。

    P2-10 回归：若首次失败仍长期占用 key，客户端用同 key 重试会被 409/4002 误拦；
    此处断言重试**不是 409/4002**，而是再次走到业务校验（422/2001）。
    """
    headers = {**authed["headers"], "Idempotency-Key": f"fail-release-{uuid4().hex}"}
    first = await db_client.post("/api/track", headers=headers, json={"events": []})
    assert (first.status_code, first.json()["code"]) == (
        422,
        ErrorCode.VALIDATION_ERROR,
    ), first.text

    second = await db_client.post("/api/track", headers=headers, json={"events": []})
    assert second.status_code != 409, second.text
    assert second.json()["code"] == ErrorCode.VALIDATION_ERROR, second.text


async def test_login_repeat_submission_single_user(db_client, db_session):
    """登录重复提交：同一 code 1 秒内 10 次 → 同一用户（openid 幂等），不重复建号。"""
    user_ids = []
    for _ in range(REPLAY_TIMES):
        resp = await db_client.post("/api/auth/login", json={"code": "replay-login-same-code"})
        assert resp.json()["code"] == 0
        user_ids.append(resp.json()["data"]["user"]["id"])
    assert len(set(user_ids)) == 1, f"同一 code 生成了多个用户: {set(user_ids)}"
    assert await db_session.scalar(select(func.count()).select_from(User)) == 1


async def test_pay_replay_state_machine_blocks_second(db_app, db_client, db_session, authed):
    """支付重复提交：PAY_MOCK_MODE 下首次推进(2)，后续 2001（订单状态机天然防重复推进）。

    【说明】该保护来自订单状态机而非独立重放防护：真实支付路径(pay 仅拉起不推进)下，
    重复拉起仍会各返回一次支付参数（无短窗去重）。
    """
    from app.core.config import get_settings
    from tests.conftest import make_settings

    db_app.dependency_overrides[get_settings] = lambda: make_settings(PAY_MOCK_MODE=True)
    merchant, sku = await _seed_merchant_sku(db_session)
    created = await db_client.post(
        "/api/order",
        headers=authed["headers"],
        json={"merchant_id": merchant.id, "items": [{"sku_id": sku.id, "qty": 1}]},
    )
    order_id = created.json()["data"]["order_id"]

    codes = []
    for _ in range(REPLAY_TIMES):
        resp = await db_client.post(f"/api/order/{order_id}/pay", headers=authed["headers"])
        codes.append((resp.status_code, resp.json()["code"]))
    assert codes[0] == (200, 0)
    assert all(c == (422, 2001) for c in codes[1:]), codes
    # app 会话已提交；populate_existing 强制用 DB 行刷新
    order = (
        await db_session.execute(
            select(Order).where(Order.id == order_id).execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert order.status == 2  # 仅推进一次
