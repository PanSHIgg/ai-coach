"""测试装配：httpx AsyncClient + app fixture（纯接口测试，不依赖 PG/Redis）。

- Settings 显式构造（_env_file=None），不受本机环境变量/.env 影响
- WECHAT_* 清空走 mock code2session
- 默认关闭限流；限流用例单独开低阈值 app

Phase 1 增补（DB 基建，供全后端复用）：
- `db_engine` / `db_session`：真实 PostgreSQL（DSN 取环境变量 DATABASE_URL，
  默认本地 127.0.0.1:5432/ai_coach），函数级清空业务表保证隔离；
- `db_app` / `db_client`：同上 app，但请求走真实 DB（get_db 依赖）；
- `authed`：预置 user + user_benefit，返回 (user_id, 认证请求头)。

运行前置：`psql -f data/sql/001_schema.sql`（或 alembic upgrade head）已建表。
"""

import os

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# 防本机 env 干扰（pydantic-settings 会读 os.environ）
for _k in ("WECHAT_APPID", "WECHAT_SECRET", "JWT_SECRET", "JWT_ALGORITHM"):
    os.environ.pop(_k, None)

# Phase 1：DB 基建指向本地 PG（真实 schema），可用环境变量覆盖。
# 注意：不覆盖 REDIS_URL——限流用例需 Redis 不可达以走进程内兜底（见 make_settings）。
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/ai_coach")

from app.core.config import Settings  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import User, UserBenefit  # noqa: E402

DB_URL = os.environ["DATABASE_URL"]

# 函数级清空的业务表（Phase 1 + Phase 3 域）；RESTART IDENTITY 保证 id 从 1 起。
# CASCADE 使外键顺序无关；"order" 为保留字需引号；sku_catalog 为参照数据不清。
_TRUNCATE_TABLES = (
    "daily_snapshot",
    "meal_record",
    "sport_record",
    "step_record",
    "weight_record",
    "subscription",
    "food_alias",
    "food",
    "body_profile",
    "invite",
    "user_benefit",
    "user_auth",
    '"user"',
    # Phase 3 交易/商家域
    "redeem_log",
    "order_item",
    '"order"',
    "coupon",
    "coupon_pool",
    "merchant_sku",
    "merchant",
    "admin_user",
    # Phase 4 社区/社交域（子表先于父表：comment/like 先于 post，challenge_join 先于 challenge）
    "community_comment",
    "community_like",
    "community_post",
    "community_group",
    "supervise",
    "battle",
    "challenge_join",
    "challenge",
    "leaderboard",
    "review",
)


def make_settings(**overrides) -> Settings:
    defaults = dict(
        LOG_LEVEL="WARNING",
        RATE_LIMIT_ENABLED=False,
        DATABASE_URL=DB_URL,
        REDIS_URL="redis://127.0.0.1:6390/0",  # 不可达端口 → 限流走进程内兜底
    )
    defaults.update(overrides)
    return Settings(_env_file=None, **defaults)


@pytest_asyncio.fixture
async def app() -> FastAPI:
    return create_app(make_settings())


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncClient:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        yield c


# ---------------------------------------------------------------------------
# DB 基建
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine(DB_URL, pool_pre_ping=True)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncSession:
    """真实 DB 会话（函数级清空业务表）。"""
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        await session.execute(
            text(f"TRUNCATE {', '.join(_TRUNCATE_TABLES)} RESTART IDENTITY CASCADE")
        )
        await session.commit()
        yield session


@pytest_asyncio.fixture
async def db_app(db_engine) -> FastAPI:
    """走真实 DB 的 app：override get_db 复用同一 engine。"""
    from app.db.session import get_db

    maker = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _get_db():
        async with maker() as session:
            yield session

    application = create_app(make_settings())
    application.dependency_overrides[get_db] = _get_db
    return application


@pytest_asyncio.fixture
async def db_client(db_app: FastAPI) -> AsyncClient:
    async with AsyncClient(transport=ASGITransport(app=db_app), base_url="http://testserver") as c:
        yield c


@pytest_asyncio.fixture
async def authed(db_session: AsyncSession) -> dict:
    """预置登录用户：返回 {"user_id": int, "headers": {...}}。"""
    user = User(openid=f"test-openid-{id(db_session)}", nickname="测试减友", gender=1)
    db_session.add(user)
    await db_session.flush()
    db_session.add(UserBenefit(user_id=user.id, tier=0, ai_times_left=10))
    await db_session.commit()
    token = create_access_token(str(user.id), openid=user.openid)
    return {"user_id": user.id, "headers": {"Authorization": f"Bearer {token}"}}


@pytest_asyncio.fixture
async def admin_authed(db_session: AsyncSession) -> dict:
    """预置超管账号（role=1，Phase 3）。

    只负责建账号并返回明文凭据；token 请在测试内通过 /api/admin/login 获取
    （与 C 端 JWT 体系解耦，不预设 admin token 的签名方式）。
    """
    from app.core.security import hash_password
    from app.models import AdminUser

    cred = {"username": f"root-{id(db_session)}", "password": "Admin@123456"}
    db_session.add(
        AdminUser(
            username=cred["username"],
            password_hash=hash_password(cred["password"]),
            role=1,
        )
    )
    await db_session.commit()
    return cred
