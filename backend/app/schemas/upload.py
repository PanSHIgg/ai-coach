"""上传域 schema（openapi: /api/upload/credential）。

COS 公开读 / 私有写：前端凭后端签发的 STS 临时密钥直传（对象键限本场景前缀），
读走公开读 URL。COS 未配置时 `configured=false`、`credentials=null`（明确降级，不伪造可用）。
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

# 场景 → COS 对象键前缀（与 openapi.yaml UploadScene 一一对应）
UploadScene = Literal["meal", "avatar", "post", "merchant"]
# 允许的文件扩展名（与 openapi.yaml UploadFileExt 一一对应）
UploadFileExt = Literal["jpg", "jpeg", "png", "webp"]


class UploadCredentialIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    scene: UploadScene
    ext: UploadFileExt = "jpg"


class StsCredentials(BaseModel):
    """腾讯云 STS 临时密钥（限定本场景前缀 + PutObject，私有写）。"""

    model_config = ConfigDict(from_attributes=True)

    tmp_secret_id: str
    tmp_secret_key: str
    session_token: str
    start_time: int  # Unix 秒
    expired_time: int  # Unix 秒


class UploadCredentialData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    configured: bool
    bucket: str
    region: str
    key: str
    public_url: str
    credentials: StsCredentials | None = None
