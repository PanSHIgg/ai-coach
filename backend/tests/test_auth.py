"""认证域测试：登录 code 换 token（code2session 由 conftest 打桩）、
无微信凭证 → HTTP 401/1001（文案不外泄配置项名）、无/坏 token 1001。"""

import pytest
from httpx import AsyncClient

# 收集期（fixture 打桩之前）绑定真实实现：autouse 打桩只替换模块属性，改不到这个引用，
# 故下方用例可验证真实的「无凭证即明确失败」守卫。
from app.services.auth_service import code2session as _real_code2session
from tests.conftest import make_settings


async def test_login_without_credentials_http_401_1001(client, monkeypatch: pytest.MonkeyPatch):
    """HTTP 层缺凭证守卫：401 + code=1001 + 通用文案（不把配置项名投给终端用户）。

    conftest 的 autouse `_stub_code2session` 会把桩装在模块属性上，这里把真实实现装回去，
    请求才会落到 `code2session` 的「无凭证即明确失败」分支（该分支此前只在服务层断过，
    HTTP 层从未执行——CI 与本机的 401 都来自微信拒假 code，不是这条守卫）。
    同时钉死 settings：`login()` 内是 `settings or get_settings()`，不注入就会吃到进程级
    默认 Settings（本机根 .env 有真凭证 → 会真打 api.weixin.qq.com）。
    """
    from app.services import auth_service

    no_credential_settings = make_settings(WECHAT_APPID="", WECHAT_SECRET="")
    monkeypatch.setattr(auth_service, "get_settings", lambda: no_credential_settings)
    monkeypatch.setattr(auth_service, "code2session", _real_code2session)

    resp = await client.post("/api/auth/login", json={"code": "no-credential-code"})

    assert resp.status_code == 401, resp.text
    body = resp.json()
    assert body["code"] == 1001, resp.text
    # 防回归锁：部署配置项名绝不出现在给用户的 message 里（login.vue 原样 toast e.message）
    message = body["message"]
    assert "WECHAT_APPID" not in message and "WECHAT_SECRET" not in message, resp.text
    assert message == "登录服务未就绪，请稍后重试", resp.text


async def test_code2session_without_credentials_fails_1001():
    """WECHAT_APPID/SECRET 为空 → 明确 1001/401，不再静默派生 openid（mock 分支已删除）。"""
    from app.core.errors import AppException

    settings = make_settings(WECHAT_APPID="", WECHAT_SECRET="")
    with pytest.raises(AppException) as excinfo:
        await _real_code2session("any-code", settings)
    assert excinfo.value.code == 1001
    assert excinfo.value.http_status == 401


async def test_me_without_token_1001(client: AsyncClient):
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401
    assert resp.json()["code"] == 1001


async def test_me_with_garbage_token_1001(client: AsyncClient):
    resp = await client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert resp.status_code == 401
    assert resp.json()["code"] == 1001
