"""IS-007: admin 登录锁定端到端测试。

5 次错误密码后第 6 次即使密码正确也返回 429/429（RATE_LIMITED）。
需要真实 Redis（db 11）才能运行；Redis 不可用时 skip。
"""

import os

import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import hash_password
from app.db import redis as redis_mod
from app.db.session import get_db
from app.main import create_app
from app.models import AdminUser
from tests.conftest import make_settings

TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://127.0.0.1:6379/11")


@pytest_asyncio.fixture
async def lockout_client(db_engine, db_session: AsyncSession):
    """使用真实 Redis db 11 的 app client，用于测试登录锁定。"""
    # 检查 Redis 可用性
    try:
        r = aioredis.from_url(TEST_REDIS_URL, decode_responses=True)
        await r.ping()
        await r.aclose()
    except Exception:
        pytest.skip(f"Redis {TEST_REDIS_URL} 不可用，跳过锁定测试")

    settings = make_settings(REDIS_URL=TEST_REDIS_URL)

    # 直接设置 redis 客户端，绕过 get_settings() 的 lru_cache
    old_client = redis_mod._client
    old_init_failed = redis_mod._init_failed
    old_last_fail_ts = redis_mod._last_fail_ts

    # 创建并设置我们的 Redis 客户端
    test_redis = aioredis.from_url(
        TEST_REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=0.5,
        socket_timeout=0.5,
    )
    redis_mod._client = test_redis
    redis_mod._init_failed = False
    redis_mod._last_fail_ts = 0.0

    # 清理测试前的残留 keys（确保测试幂等性）
    try:
        keys = await test_redis.keys("admin_login_*")
        if keys:
            await test_redis.delete(*keys)
    except Exception:
        pass

    maker = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _get_db():
        async with maker() as session:
            yield session

    application = create_app(settings)
    application.dependency_overrides[get_db] = _get_db

    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://testserver"
    ) as c:
        yield c

    # 清理：清除测试用的 Redis keys
    try:
        keys = await test_redis.keys("admin_login_*")
        if keys:
            await test_redis.delete(*keys)
        await test_redis.aclose()
    except Exception:
        pass

    # 恢复 redis 模块状态
    redis_mod._client = old_client
    redis_mod._init_failed = old_init_failed
    redis_mod._last_fail_ts = old_last_fail_ts


async def test_admin_login_lockout_after_5_failures(
    db_session: AsyncSession, lockout_client: AsyncClient
):
    """IS-007: 5 次错误密码后锁定，第 6 次正确密码也返回 429。"""
    username = "lockout-test-admin"
    password = "Correct@123456"

    # 创建 admin 用户
    db_session.add(
        AdminUser(
            username=username,
            password_hash=hash_password(password),
            role=1,
        )
    )
    await db_session.commit()

    # 5 次错误密码
    for i in range(5):
        r = await lockout_client.post(
            "/api/admin/login",
            json={"username": username, "password": f"Wrong@{i}"},
        )
        assert r.status_code == 401, f"第 {i+1} 次错误密码应返回 401"
        assert r.json()["code"] == 1001

    # 第 6 次：即使密码正确也应被锁定
    r = await lockout_client.post(
        "/api/admin/login",
        json={"username": username, "password": password},
    )
    assert r.status_code == 429, f"锁定后应返回 429，实际: {r.status_code}, body: {r.text}"
    assert r.json()["code"] == 429, f"业务码应为 429，实际: {r.json()}"


async def test_admin_login_lockout_ttl_positive(
    db_session: AsyncSession, lockout_client: AsyncClient
):
    """IS-007: 锁定后 fail 和 lock key 都应有正 TTL（非永久 key）。"""
    username = "ttl-test-admin"
    password = "Correct@123456"

    db_session.add(
        AdminUser(
            username=username,
            password_hash=hash_password(password),
            role=1,
        )
    )
    await db_session.commit()

    # 5 次错误密码触发锁定
    for i in range(5):
        await lockout_client.post(
            "/api/admin/login",
            json={"username": username, "password": f"Wrong@{i}"},
        )

    # 验证 lock key 存在且有 TTL
    test_redis = aioredis.from_url(TEST_REDIS_URL, decode_responses=True)
    lock_key = f"admin_login_lock:{username}"
    fail_key = f"admin_login_fail:{username}"

    lock_ttl = await test_redis.ttl(lock_key)
    assert lock_ttl > 0, f"lock key 应有正 TTL，实际: {lock_ttl}"

    # fail key 在达到阈值后应被删除
    fail_exists = await test_redis.exists(fail_key)
    assert fail_exists == 0, f"达到阈值后 fail key 应被删除，实际存在: {fail_exists}"

    await test_redis.aclose()


async def test_admin_login_redis_unavailable_degrades(
    db_session: AsyncSession, db_engine
):
    """IS-007: Redis 不可用时登录应降级（不锁定），错误密码仍返回 401。"""
    # 使用不可达的 Redis URL
    unavailable_redis = "redis://127.0.0.1:6399/0"

    try:
        r = aioredis.from_url(unavailable_redis, decode_responses=True)
        await r.ping()
        await r.aclose()
        pytest.skip(f"Redis {unavailable_redis} 意外可用，跳过降级测试")
    except Exception:
        pass

    settings = make_settings(REDIS_URL=unavailable_redis)

    old_client = redis_mod._client
    old_init_failed = redis_mod._init_failed
    old_last_fail_ts = redis_mod._last_fail_ts

    # 设置为不可达的 Redis
    test_redis = aioredis.from_url(
        unavailable_redis,
        decode_responses=True,
        socket_connect_timeout=0.1,
        socket_timeout=0.1,
    )
    redis_mod._client = test_redis
    redis_mod._init_failed = True
    redis_mod._last_fail_ts = 0.0

    maker = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _get_db():
        async with maker() as session:
            yield session

    application = create_app(settings)
    application.dependency_overrides[get_db] = _get_db

    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://testserver"
    ) as client:
        username = "degrade-test-admin"
        password = "Correct@123456"

        db_session.add(
            AdminUser(
                username=username,
                password_hash=hash_password(password),
                role=1,
            )
        )
        await db_session.commit()

        # 多次错误密码，不应触发锁定（Redis 不可用）
        for i in range(10):
            r = await client.post(
                "/api/admin/login",
                json={"username": username, "password": f"Wrong@{i}"},
            )
            assert r.status_code == 401, f"Redis 不可用时错误密码应返回 401，实际: {r.status_code}"
            assert r.json()["code"] == 1001

        # 正确密码应能登录成功（无锁定）
        r = await client.post(
            "/api/admin/login",
            json={"username": username, "password": password},
        )
        assert r.status_code == 200, f"Redis 不可用时正确密码应能登录，实际: {r.status_code}"
        assert r.json()["code"] == 0

    # 恢复 redis 模块状态
    await test_redis.aclose()
    redis_mod._client = old_client
    redis_mod._init_failed = old_init_failed
    redis_mod._last_fail_ts = old_last_fail_ts
