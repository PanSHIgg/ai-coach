"""认证域测试：mock 登录换 token、/auth/me 带 token、无/坏 token 1001。"""

from httpx import AsyncClient


async def _login(client: AsyncClient) -> str:
    resp = await client.post("/api/auth/login", json={"code": "test-code-123"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0 and body["data"]["token"]
    return body["data"]["token"]


async def test_login_mock_and_me(client: AsyncClient):
    resp = await client.post("/api/auth/login", json={"code": "test-code-123"})
    body = resp.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["is_new"] is True and data["need_profile"] is True
    assert data["user"]["id"] > 0

    me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {data['token']}"})
    assert me.status_code == 200
    assert me.json()["code"] == 0
    assert me.json()["data"]["id"] == data["user"]["id"]


async def test_login_deterministic_mock_openid(client: AsyncClient):
    """同一 code 两次登录 → 同一 openid → 同一用户 id（mock 确定性）。"""
    r1 = await client.post("/api/auth/login", json={"code": "same-code"})
    r2 = await client.post("/api/auth/login", json={"code": "same-code"})
    assert r1.json()["data"]["user"]["id"] == r2.json()["data"]["user"]["id"]


async def test_me_without_token_1001(client: AsyncClient):
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401
    assert resp.json()["code"] == 1001


async def test_me_with_garbage_token_1001(client: AsyncClient):
    resp = await client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert resp.status_code == 401
    assert resp.json()["code"] == 1001
