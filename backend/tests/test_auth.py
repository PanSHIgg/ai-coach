"""认证域测试：mock 登录换 token、/auth/me 带 token、无/坏 token 1001。"""

from httpx import AsyncClient


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
