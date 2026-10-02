"""测试装配：httpx AsyncClient + app fixture（纯接口测试，不依赖 PG/Redis）。

- Settings 显式构造（_env_file=None），不受本机环境变量/.env 影响
- WECHAT_* 从环境清除 + code2session 打桩：用例永不访问 api.weixin.qq.com
- 默认关闭限流；限流用例单独开低阈值 app

Phase 1 增补（DB 基建，供全后端复用）：
- `db_engine` / `db_session`：真实 PostgreSQL（DSN 取环境变量 DATABASE_URL，
  默认本地 127.0.0.1:5432/ai_coach），函数级清空业务表保证隔离；
- `db_app` / `db_client`：同上 app，但请求走真实 DB（get_db 依赖）；
- `authed`：预置 user + user_benefit，返回 (user_id, 认证请求头)。

运行前置：`psql -f data/sql/001_schema.sql`（或 alembic upgrade head）已建表。
"""

import hashlib
import os

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# 防本机 env 干扰（pydantic-settings 会读 os.environ）。
# WECHAT_APPID/SECRET 一并清除：凡以微信凭证为降级判据的路径（content_security 文本/图片审核、
# 订阅消息发送、步数解密）在测试中一律走离线确定性分支；登录侧 code2session 由下方
# _stub_code2session 打桩接管，auth_service 无凭证时是**明确 1001 失败**（不再有 mock 分支）。
for _k in ("WECHAT_APPID", "WECHAT_SECRET", "JWT_SECRET", "JWT_ALGORITHM"):
    os.environ.pop(_k, None)

# Phase 1：DB 基建指向本地 PG（真实 schema），可用环境变量覆盖。
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/ai_coach")
# Phase 5：测试进程内禁用连接池。app 引擎是**进程级单例**，而 pytest 每个用例独立事件循环；
# 一旦引擎以带池方式创建（如某用例走默认 Settings），该池即绑定到那个 loop，后续用例复用会报
# 「attached to a different loop」。此处用环境变量兜住所有 Settings 构造路径（含默认 Settings）。
os.environ.setdefault("DB_POOL_DISABLED", "true")

# REDIS_URL 硬赋值（非 setdefault）：隔离测试与外部环境——Settings 默认值是
# redis://redis:6379/0（compose 主机名），在容器网络中（如 act_runner 的 service
# 别名恰为 redis、CI 传 redis://127.0.0.1:6379/0）该值会**意外可达**，令限流/AI
# 配额用例走真实 Redis，跨事件循环复用连接 + 计数跨用例累积 → 「RuntimeError:
# Event loop is closed」/ 429（2026-09-30 本地 + Gitea CI 双环境复现）。
# 故此处对含默认 Settings() 在内的所有构造路径统一钉死为**不可达端口**，用例
# 一律走「Redis 不可达 → 进程内兜底」的确定性路径，不受外部 REDIS_URL 影响；
# 限流用例依赖的内存兜底见 make_settings。
os.environ["REDIS_URL"] = "redis://127.0.0.1:6390/0"

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
    # Phase 5 埋点域
    "track_event",
    # 0010：我的页 5 模块 + 商家自助后台（G3/G11）
    "user_points",
    "points_log",
    "daily_checkin",
    "user_task",
    "user_privacy",
    "exclusive_offer",
    "report_export",
    "merchant_account",
    # 0010：记录归档分区父表（G8；TRUNCATE 父表级联清空各分区）
    "meal_record_archive",
    "sport_record_archive",
    "weight_record_archive",
    "step_record_archive",
    "daily_snapshot_archive",
    "track_event_archive",
    "ai_dialog_archive",
)


def make_settings(**overrides) -> Settings:
    defaults = dict(
        LOG_LEVEL="WARNING",
        RATE_LIMIT_ENABLED=False,
        DATABASE_URL=DB_URL,
        REDIS_URL="redis://127.0.0.1:6390/0",  # 不可达端口 → 限流走进程内兜底
        # 测试用：app 级引擎回退 NullPool。pytest 每个用例独立事件循环，而 app 引擎是
        # 模块级单例，复用连接池会报「attached to a different loop」（Phase 5 改池后暴露）。
        # 生产单 loop 运行，走真实连接池（见 perf/report.md）。
        DB_POOL_DISABLED=True,
    )
    defaults.update(overrides)
    return Settings(_env_file=None, **defaults)


@pytest.fixture(autouse=True)
def _reset_rate_limit_memory():
    """用例级清理进程内限流兜底存储（Redis 不可达时启用）。

    否则同一 key（如 `ai:chat:user:1`，用户 id 经 RESTART IDENTITY 每用例都为 1）
    的计数会在 60s 窗口内跨用例累积，令「子集运行」与「全量运行」结论不一致
    （F1-3：test_ai_chat 限流用例残留计数导致后续冒烟用例得 429 而非 409）。
    """
    from app.core.rate_limit import _memory_windows

    _memory_windows.clear()
    yield
    _memory_windows.clear()


@pytest.fixture(autouse=True)
def _stub_code2session(monkeypatch: pytest.MonkeyPatch) -> None:
    """打桩 auth_service.code2session：任何用例都不许真打 api.weixin.qq.com。

    auth_service 已删除"无凭证 → openid=md5(code)"的 mock 分支（无凭证是明确 1001 失败），
    登录侧的零依赖可跑性改由此处承担：openid = "test-" + sha256(code)[:16]，
    **同 code 必得同 openid**——test_security_replay（同 code 提交 10 次只建 1 用户）与
    test_security_sqli（8 条注入串当作不透明 code）都依赖该确定性，随机 openid 会假失败。
    返回体不带 mock 标记：真实 code2session 已不返回该字段，桩与其同形。
    """
    from app.services import auth_service

    async def _fake(code: str, settings=None) -> dict:
        return {
            "openid": "test-" + hashlib.sha256(code.encode("utf-8")).hexdigest()[:16],
            "session_key": "",
            "unionid": None,
        }

    monkeypatch.setattr(auth_service, "code2session", _fake)


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
