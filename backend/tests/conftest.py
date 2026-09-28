"""测试装配：httpx AsyncClient + app fixture（纯接口测试，不依赖 PG/Redis）。

- Settings 显式构造（_env_file=None），不受本机环境变量/.env 影响
- WECHAT_* 清空走 mock code2session
- 默认关闭限流；限流用例单独开低阈值 app
"""

import os

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

# 防本机 env 干扰（pydantic-settings 会读 os.environ）
for _k in ("WECHAT_APPID", "WECHAT_SECRET", "JWT_SECRET", "JWT_ALGORITHM"):
    os.environ.pop(_k, None)

from app.core.config import Settings
from app.main import create_app


def make_settings(**overrides) -> Settings:
    defaults = dict(
        LOG_LEVEL="WARNING",
        RATE_LIMIT_ENABLED=False,
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
