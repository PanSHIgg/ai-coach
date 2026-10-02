"""上传域接口（openapi: /api/upload/credential）。

COS 公开读 / 私有写：登录用户按场景申请 **STS 临时密钥**，小程序凭此直传 COS，
图片字节不经后端；对象键限本场景前缀，读走公开读 URL。
"""

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, get_current_user, get_request_id
from app.core.config import Settings, get_settings
from app.schemas import Envelope, UploadCredentialData, UploadCredentialIn
from app.schemas.common import ok
from app.services import storage

router = APIRouter(tags=["上传"])


@router.post(
    "/upload/credential",
    response_model=Envelope[UploadCredentialData],
    summary="获取 COS 直传临时凭证（STS；公开读/私有写）",
)
async def get_upload_credential(
    payload: UploadCredentialIn,
    user: CurrentUser = Depends(get_current_user),
    request_id: str | None = Depends(get_request_id),
    settings: Settings = Depends(get_settings),
) -> Envelope[UploadCredentialData]:
    """已登录用户按场景申请直传凭证；COS 未配置 → configured=false（明确降级，不签发密钥）。"""
    data = await storage.issue_upload_credential(payload.scene, payload.ext, settings)
    return ok(data, request_id=request_id)
