"""COS 对象存储直传（腾讯云 STS 临时密钥）。

docs/split/04 §6.1/§6.3.2、06 §2.3：食物照片、商家图、用户头像统一存腾讯云 COS。

**桶策略：公开读 / 私有写**——
- 读：对象经 `COS_BASE_URL`（自定义域名/CDN）或 bucket 域名公开可读；
- 写：后端签发 **STS 临时密钥**（仅限本场景对象键前缀 + `cos:PutObject`），
  小程序凭此**直传 COS**，图片字节不经后端。

未配置（`COS_SECRET_ID`/`COS_SECRET_KEY`/`COS_BUCKET` 任一为空）→ **明确降级**：
`configured=false`、`credentials=null`，前端跳过直传（不伪造可用、不崩），与仓库
「未配置即降级」的一致口径（见 `app/ai/README.md`）。
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from app.core.config import Settings
from app.core.errors import AppException
from app.schemas.common import ErrorCode
from app.schemas.upload import StsCredentials, UploadCredentialData

# 上传场景 → 对象键前缀（与 openapi UploadScene 一致）
SCENES = ("meal", "avatar", "post", "merchant")
# 允许的扩展名（与 openapi UploadFileExt 一致）
ALLOWED_EXT = ("jpg", "jpeg", "png", "webp")


@dataclass(frozen=True)
class StsCredential:
    """STS 临时密钥（厂商无关的最小字段集）。"""

    tmp_secret_id: str
    tmp_secret_key: str
    session_token: str
    start_time: int
    expired_time: int


class StsProvider(Protocol):
    """签发 COS 直传临时密钥的抽象；真实实现走腾讯云 STS，测试可注入假实现。"""

    def issue(self, *, bucket: str, region: str, prefix: str, duration: int) -> StsCredential: ...


def is_configured(settings: Settings) -> bool:
    """COS 三要素齐备才算已配置（缺一即降级）。"""
    return bool(settings.COS_SECRET_ID and settings.COS_SECRET_KEY and settings.COS_BUCKET)


def build_object_key(
    scene: str, ext: str, *, token: str | None = None, now: datetime | None = None
) -> str:
    """对象键：`{scene}/{YYYY}/{MM}/{DD}/{uuid}.{ext}`（按日分区，便于归档与 CDN 缓存）。"""
    ts = now or datetime.now(UTC)
    return f"{scene}/{ts:%Y/%m/%d}/{token or uuid.uuid4().hex}.{ext}"


def public_url_for(key: str, settings: Settings) -> str:
    """对象键 → 公开读 URL（自定义域名优先，否则 bucket 默认域名）。"""
    base = (
        settings.COS_BASE_URL
        or f"https://{settings.COS_BUCKET}.cos.{settings.COS_REGION}.myqcloud.com"
    ).rstrip("/")
    return f"{base}/{key}"


class QcloudStsProvider:
    """腾讯云 STS 实现（qcloud-python-sts；同步 SDK，调用处放线程池）。"""

    def __init__(self, secret_id: str, secret_key: str) -> None:
        self._secret_id = secret_id
        self._secret_key = secret_key

    def issue(self, *, bucket: str, region: str, prefix: str, duration: int) -> StsCredential:
        # 延迟导入：未配置/未安装 SDK 时不阻断模块加载（凭证接口走降级分支）
        from sts.sts import Sts

        config = {
            "secret_id": self._secret_id,
            "secret_key": self._secret_key,
            "bucket": bucket,
            "region": region,
            "duration_seconds": duration,
            "allow_prefix": [prefix],  # 仅限本场景目录，最小权限
            "allow_actions": ["name/cos:PutObject"],  # 私有写：只允许上传
        }
        data = Sts(config).get_credential()
        cred = data["credentials"]
        return StsCredential(
            tmp_secret_id=cred["tmpSecretId"],
            tmp_secret_key=cred["tmpSecretKey"],
            session_token=cred["sessionToken"],
            start_time=int(data["startTime"]),
            expired_time=int(data["expiredTime"]),
        )


def sts_provider_for(settings: Settings) -> StsProvider:
    """按 env 装配 STS 客户端（仅在已配置时调用）。"""
    return QcloudStsProvider(settings.COS_SECRET_ID, settings.COS_SECRET_KEY)


async def issue_upload_credential(
    scene: str,
    ext: str,
    settings: Settings,
    *,
    provider: StsProvider | None = None,
) -> UploadCredentialData:
    """签发直传凭证；未配置 → `configured=false`（明确降级，不签发任何密钥）。"""
    if not is_configured(settings):
        return UploadCredentialData(
            configured=False,
            bucket="",
            region=settings.COS_REGION,
            key="",
            public_url="",
            credentials=None,
        )

    key = build_object_key(scene, ext)
    prov = provider or sts_provider_for(settings)
    try:
        cred = await asyncio.to_thread(
            prov.issue,
            bucket=settings.COS_BUCKET,
            region=settings.COS_REGION,
            # 资源前缀须带通配（scene/*）才能匹配该场景目录下的对象键（最小权限）
            prefix=f"{scene}/*",
            duration=settings.COS_STS_DURATION,
        )
    except Exception as exc:  # 网络/签名/权限错误统一 500，不泄露厂商细节
        raise AppException(ErrorCode.SERVER_ERROR, "对象存储暂不可用，请稍后再试") from exc

    return UploadCredentialData(
        configured=True,
        bucket=settings.COS_BUCKET,
        region=settings.COS_REGION,
        key=key,
        public_url=public_url_for(key, settings),
        credentials=StsCredentials(
            tmp_secret_id=cred.tmp_secret_id,
            tmp_secret_key=cred.tmp_secret_key,
            session_token=cred.session_token,
            start_time=cred.start_time,
            expired_time=cred.expired_time,
        ),
    )
