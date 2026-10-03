"""COS 直传凭证 + 头像更新测试（COS 集成）。

独立成文理由：`/api/upload/credential` 与 `/api/user/avatar` 是本次 COS 集成新增行为，
与既有 `test_profile`（身体档案）/`test_auth`（登录）主题不同，混写会稀释主题。

分层（禁止真实联网，STS 一律注入假实现）：
- 纯逻辑：对象键格式、公开 URL、已配置判定——不连库不联网；
- 接口行为：鉴权 401、入参 422、未配置降级、已配置签发 STS、STS 失败 500、
  头像更新与回显——走 client/db_client + authed。
"""

from datetime import UTC, datetime

import pytest

from app.core.config import Settings, get_settings
from app.services import storage

# 纯逻辑


def test_build_object_key_partitions_by_day():
    key = storage.build_object_key(
        "meal", "png", token="deadbeef", now=datetime(2026, 10, 2, tzinfo=UTC)
    )
    assert key == "meal/2026/10/02/deadbeef.png"


def test_build_object_key_uses_uuid_when_token_absent():
    scene, ext = "avatar", "jpg"
    key = storage.build_object_key(scene, ext)
    prefix, _, name = key.rpartition("/")
    assert prefix == "avatar" or prefix.startswith("avatar/")
    assert name.endswith(".jpg") and len(name) > len(".jpg")


@pytest.mark.parametrize(
    "base,expect",
    [
        ("", "https://b-125.cos.ap-guangzhou.myqcloud.com/meal/x.jpg"),
        ("https://cdn.example.com/", "https://cdn.example.com/meal/x.jpg"),
    ],
    ids=["bucket_domain", "custom_base"],
)
def test_public_url_for(base, expect):
    settings = Settings(
        _env_file=None, COS_BUCKET="b-125", COS_REGION="ap-guangzhou", COS_BASE_URL=base
    )
    assert storage.public_url_for("meal/x.jpg", settings) == expect


@pytest.mark.parametrize(
    "kwargs,expect",
    [
        (dict(), False),  # 三要素全空
        (dict(COS_SECRET_ID="id"), False),  # 缺 key/bucket
        (dict(COS_SECRET_ID="id", COS_SECRET_KEY="key"), False),  # 缺 bucket
        (dict(COS_SECRET_ID="id", COS_SECRET_KEY="key", COS_BUCKET="b-125"), True),
    ],
    ids=["empty", "id_only", "no_bucket", "all_set"],
)
def test_is_configured_requires_all_three(kwargs, expect):
    assert storage.is_configured(Settings(_env_file=None, **kwargs)) is expect


# 接口行为


@pytest.mark.parametrize(
    "path,payload",
    [
        ("/api/upload/credential", {"scene": "meal"}),
        ("/api/user/avatar", {"avatar_url": "https://cos.example.com/a.jpg"}),
    ],
)
async def test_cos_endpoints_require_auth(client, path, payload):
    resp = await client.post(path, json=payload)
    assert resp.status_code == 401
    assert resp.json()["code"] == 1001


@pytest.mark.parametrize(
    "payload",
    [
        {"scene": "unknown"},  # 非枚举场景
        {"scene": "meal", "ext": "gif"},  # 非允许扩展名
        {},  # 缺 scene
    ],
    ids=["bad_scene", "bad_ext", "missing_scene"],
)
async def test_upload_credential_rejects_invalid_input(db_client, authed, payload):
    resp = await db_client.post("/api/upload/credential", headers=authed["headers"], json=payload)
    assert resp.status_code == 422
    assert resp.json()["code"] == 2001


async def test_upload_credential_degrades_when_unconfigured(db_client, authed):
    """COS 三要素为空 → configured=false 且不签发任何密钥（明确降级，不伪造可用）。"""
    resp = await db_client.post(
        "/api/upload/credential", headers=authed["headers"], json={"scene": "meal"}
    )
    assert resp.status_code == 200 and resp.json()["code"] == 0
    data = resp.json()["data"]
    assert data["configured"] is False
    assert data["credentials"] is None
    assert data["key"] == "" and data["public_url"] == ""


class _FakeSts:
    """假 STS：记录入参并返回固定临时密钥（不联网）。"""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[dict] = []

    def issue(self, *, bucket: str, region: str, prefix: str, duration: int):
        self.calls.append(
            {"bucket": bucket, "region": region, "prefix": prefix, "duration": duration}
        )
        if self.error is not None:
            raise self.error
        return storage.StsCredential("tmp-id", "tmp-key", "tmp-token", 1000, 2800)


def _configure_cos(db_app):
    """覆盖 get_settings → 已配置 COS；返回被覆盖时使用的 Settings。"""
    settings = Settings(
        _env_file=None,
        COS_SECRET_ID="id",
        COS_SECRET_KEY="key",
        COS_BUCKET="b-125",
        COS_REGION="ap-guangzhou",
        COS_BASE_URL="https://cdn.example.com",
        COS_STS_DURATION=1800,
    )
    db_app.dependency_overrides[get_settings] = lambda: settings
    return settings


async def test_upload_credential_issues_sts_when_configured(db_app, db_client, authed, monkeypatch):
    _configure_cos(db_app)
    fake = _FakeSts()
    monkeypatch.setattr(storage, "sts_provider_for", lambda settings: fake)

    resp = await db_client.post(
        "/api/upload/credential", headers=authed["headers"], json={"scene": "avatar", "ext": "png"}
    )
    assert resp.status_code == 200 and resp.json()["code"] == 0
    data = resp.json()["data"]
    assert data["configured"] is True
    assert data["bucket"] == "b-125" and data["region"] == "ap-guangzhou"
    # 对象键按场景前缀 + 扩展名；公开 URL 走自定义域名
    assert data["key"].startswith("avatar/") and data["key"].endswith(".png")
    assert data["public_url"] == f"https://cdn.example.com/{data['key']}"
    assert data["credentials"] == {
        "tmp_secret_id": "tmp-id",
        "tmp_secret_key": "tmp-key",
        "session_token": "tmp-token",
        "start_time": 1000,
        "expired_time": 2800,
    }
    # 临时密钥最小权限：仅本场景前缀 + 配置的有效期
    assert fake.calls == [
        {"bucket": "b-125", "region": "ap-guangzhou", "prefix": "avatar/*", "duration": 1800}
    ]


async def test_upload_credential_sts_failure_returns_500(db_app, db_client, authed, monkeypatch):
    _configure_cos(db_app)
    monkeypatch.setattr(
        storage, "sts_provider_for", lambda settings: _FakeSts(error=RuntimeError("sts down"))
    )
    resp = await db_client.post(
        "/api/upload/credential", headers=authed["headers"], json={"scene": "meal"}
    )
    assert resp.status_code == 500
    assert resp.json()["code"] == 500


async def test_update_avatar_persists_and_echoes(db_client, db_session, authed):
    resp = await db_client.post(
        "/api/user/avatar",
        headers=authed["headers"],
        json={"avatar_url": "https://cdn.example.com/avatar/1.png"},
    )
    assert resp.status_code == 200 and resp.json()["code"] == 0
    assert resp.json()["data"]["avatar_url"] == "https://cdn.example.com/avatar/1.png"
    # 回显持久化：/api/auth/me 读到新头像
    me = await db_client.get("/api/auth/me", headers=authed["headers"])
    assert me.json()["data"]["avatar_url"] == "https://cdn.example.com/avatar/1.png"


@pytest.mark.parametrize("avatar_url", ["", "x" * 513], ids=["empty", "too_long"])
async def test_update_avatar_rejects_invalid(db_client, authed, avatar_url):
    resp = await db_client.post(
        "/api/user/avatar", headers=authed["headers"], json={"avatar_url": avatar_url}
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == 2001
