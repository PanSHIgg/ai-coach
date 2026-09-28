"""BE1 认证 DB 集成测试：登录幂等/need_profile、me 真实档案、refresh 换发/失效。

均走真实 PostgreSQL（db_client + db_session），db_session 触发表清空保证隔离。
"""

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BodyProfile, User, UserAuth, UserBenefit


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
