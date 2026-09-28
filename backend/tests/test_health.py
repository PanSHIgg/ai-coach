"""健康检查与中间件行为测试。"""

from httpx import AsyncClient


async def test_healthz_ok(client: AsyncClient):
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_request_id_header(client: AsyncClient):
    resp = await client.get("/healthz", headers={"X-Request-ID": "req-test-1"})
    assert resp.headers.get("X-Request-ID") == "req-test-1"

    resp2 = await client.get("/healthz")
    assert resp2.headers.get("X-Request-ID")


async def test_unknown_route_envelope(client: AsyncClient):
    """未知路由 → 404 + envelope(3001)。"""
    resp = await client.get("/api/nope")
    assert resp.status_code == 404
    assert resp.json()["code"] == 3001
