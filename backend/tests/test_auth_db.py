"""BE1 认证 DB 集成测试：登录幂等/need_profile、me 真实档案、refresh 换发/失效、
session_key 持久化（F-09 微信运动解密的唯一密钥来源）。

均走真实 PostgreSQL（db_client + db_session），db_session 触发表清空保证隔离。
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BodyProfile, User, UserAuth, UserBenefit
from app.services import auth_service


async def _count(session: AsyncSession, model, *conditions) -> int:
    stmt = select(func.count()).select_from(model)
    for cond in conditions:
        stmt = stmt.where(cond)
    return int(await session.scalar(stmt))


async def test_login_creates_user_and_is_idempotent(
    db_session: AsyncSession, db_client: AsyncClient
):
    code = "be1-login-idempotent"
    body = (await db_client.post("/api/auth/login", json={"code": code})).json()
    assert body["code"] == 0
    first = body["data"]
    assert first["is_new"] is True
    assert first["need_profile"] is True
    assert first["user"]["id"] > 0
    assert first["token"] and first["refresh_token"]

    # 同一 openid 重复登录 → 不新建，id 不变
    again = (await db_client.post("/api/auth/login", json={"code": code})).json()["data"]
    assert again["is_new"] is False
    assert again["user"]["id"] == first["user"]["id"]

    # 幂等：同一 openid 仅 1 个 user，该 user 仅 1 条 user_auth / user_benefit
    uid = first["user"]["id"]
    openid = await db_session.scalar(select(User.openid).where(User.id == uid))
    assert await _count(db_session, User, User.openid == openid) == 1
    assert await _count(db_session, UserAuth, UserAuth.user_id == uid) == 1
    assert await _count(db_session, UserBenefit, UserBenefit.user_id == uid) == 1

    auth_row = (
        await db_session.execute(select(UserAuth).where(UserAuth.user_id == uid))
    ).scalar_one()
    assert auth_row.provider == "wechat_mp"
    benefit = (
        await db_session.execute(select(UserBenefit).where(UserBenefit.user_id == uid))
    ).scalar_one()
    assert benefit.tier == 0 and benefit.ai_times_left == 10


async def test_login_need_profile_false_after_creating_profile(
    db_session: AsyncSession, db_client: AsyncClient
):
    code = "be1-need-profile"
    first = (await db_client.post("/api/auth/login", json={"code": code})).json()["data"]
    assert first["need_profile"] is True

    db_session.add(
        BodyProfile(
            user_id=first["user"]["id"],
            gender=1,
            height_cm=175,
            current_weight=70,
            target_type=1,
            activity_level=2,
            goal_pace=1,
        )
    )
    await db_session.commit()

    again = (await db_client.post("/api/auth/login", json={"code": code})).json()["data"]
    assert again["is_new"] is False
    assert again["need_profile"] is False


async def test_me_returns_real_profile_and_benefit(
    db_session: AsyncSession, db_client: AsyncClient, authed: dict
):
    uid = authed["user_id"]
    db_session.add(
        BodyProfile(
            user_id=uid,
            gender=2,
            height_cm=162,
            birth_year=1998,
            age=28,
            current_weight=55,
            target_type=1,
            activity_level=3,
            goal_pace=1,
        )
    )
    await db_session.commit()

    resp = await db_client.get("/api/auth/me", headers=authed["headers"])
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["id"] == uid
    assert data["gender"] == 2  # 取自 body_profile
    assert data["benefit"] == {"tier": 0, "ai_times_left": 10}


async def test_me_without_profile_defaults(db_client: AsyncClient, authed: dict):
    """无档案时 gender 取 user.gender、benefit 取 user_benefit。"""
    resp = await db_client.get("/api/auth/me", headers=authed["headers"])
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["id"] == authed["user_id"]
    assert data["gender"] == 1
    assert data["benefit"]["ai_times_left"] == 10


async def test_refresh_rotates_tokens(db_client: AsyncClient):
    login = (await db_client.post("/api/auth/login", json={"code": "be1-refresh"})).json()["data"]
    resp = await db_client.post("/api/auth/refresh", json={"refresh_token": login["refresh_token"]})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["token"] and data["refresh_token"]

    me = await db_client.get("/api/auth/me", headers={"Authorization": f"Bearer {data['token']}"})
    assert me.status_code == 200
    assert me.json()["data"]["id"] == login["user"]["id"]


async def test_refresh_with_access_token_1001(db_client: AsyncClient):
    login = (await db_client.post("/api/auth/login", json={"code": "be1-refresh-bad"})).json()[
        "data"
    ]
    resp = await db_client.post("/api/auth/refresh", json={"refresh_token": login["token"]})
    assert resp.status_code == 401
    assert resp.json()["code"] == 1001


async def test_refresh_with_garbage_token_1001(db_client: AsyncClient):
    resp = await db_client.post("/api/auth/refresh", json={"refresh_token": "not-a-jwt"})
    assert resp.status_code == 401
    assert resp.json()["code"] == 1001


# F-09：登录持久化 session_key（微信运动步数解密的唯一合法密钥来源）


class _RecordingRedis:
    """只记录 set 调用的最小 Redis 替身。

    `tests/conftest.py` 把 REDIS_URL 钉成不可达端口且属禁碰文件，故以注入方式提供。
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int | None]] = []

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.calls.append((key, value, ex))


def _patch_redis(monkeypatch: pytest.MonkeyPatch, stub) -> None:
    """替换 auth_service 的 get_redis（session_key 的读写都经它）。"""

    async def _get_redis():
        return stub

    monkeypatch.setattr(auth_service, "get_redis", _get_redis)


def _patch_code2session(monkeypatch: pytest.MonkeyPatch, session_key: str) -> None:
    """覆盖 conftest 的桩，让 code2session 返回非空 session_key（真实微信必返）。"""

    async def _fake(code: str, settings=None) -> dict:
        return {"openid": f"test-{code}", "session_key": session_key, "unionid": None}

    monkeypatch.setattr(auth_service, "code2session", _fake)


async def test_login_persists_session_key_per_user_with_ttl(
    db_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """登录必须按用户持久化 code2session 的 session_key，带 TTL，且**绝不下发给客户端**。

    旧实现拿到 session_key 后直接丢弃 → 后端永远无 key 可解密，只能读静态环境变量。
    """
    recorder = _RecordingRedis()
    _patch_redis(monkeypatch, recorder)
    _patch_code2session(monkeypatch, "sk-real-from-wechat")

    resp = await db_client.post("/api/auth/login", json={"code": "werun-login"})
    body = resp.json()
    assert body["code"] == 0
    uid = body["data"]["user"]["id"]

    assert recorder.calls, "session_key 未持久化"
    key, value, ttl = recorder.calls[0]
    assert key == auth_service.session_key_redis_key(uid)
    assert f":{uid}" in key  # 按用户隔离：解密侧只能取到本人的 key
    assert value == "sk-real-from-wechat"
    # session_key 是会话态（每次 wx.login 轮换），TTL 按任务口径压到 ≤24h
    assert 0 < ttl <= 24 * 3600
    # 敏感凭据不出现在响应里（服务端绝不可下发 session_key）
    assert "sk-real-from-wechat" not in resp.text


async def test_login_succeeds_when_redis_unavailable(
    db_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Redis 不可用（get_redis → None）只让步数解密降级，**不得阻断登录**。"""
    _patch_redis(monkeypatch, None)
    _patch_code2session(monkeypatch, "sk-real-from-wechat")

    resp = await db_client.post("/api/auth/login", json={"code": "redis-down-login"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["token"]
