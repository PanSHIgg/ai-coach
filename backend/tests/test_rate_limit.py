"""限流测试：连发触发 429（envelope code=429 + Retry-After）；/healthz 不限流。"""

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from tests.conftest import make_settings


@pytest_asyncio.fixture
async def limited_client():
    app = create_app(
        make_settings(
            RATE_LIMIT_ENABLED=True,
            RATE_LIMIT_GLOBAL_PER_MIN=100,
            RATE_LIMIT_AI_PER_MIN=2,  # AI 域阈值压到 2 便于触发
            RATE_LIMIT_AUTH_PER_MIN=10,
        )
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        yield c


async def _token(client: AsyncClient) -> str:
    resp = await client.post("/api/auth/login", json={"code": "rate-test"})
    return resp.json()["data"]["token"]


async def test_ai_rate_limit_429(limited_client: AsyncClient):
    token = await _token(limited_client)
    headers = {"Authorization": f"Bearer {token}"}
    codes = []
    for _ in range(4):
        resp = await limited_client.post(
            "/api/ai/chat", json={"session_id": "s-1", "message": "饿了"}, headers=headers
        )
        codes.append(resp.status_code)
    assert codes[:2] == [200, 200]
    assert codes[2] == 429
    body = resp.json()
    assert body["code"] == 429
    assert resp.headers.get("Retry-After") == "60"


async def test_healthz_not_rate_limited(limited_client: AsyncClient):
    """/healthz 无前缀端点不受限流影响。"""
    for _ in range(5):
        resp = await limited_client.get("/healthz")
        assert resp.status_code == 200
