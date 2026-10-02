/**
 * upload API · COS 直传临时凭证（COS 集成）
 *
 * 契约：contracts/openapi.yaml /api/upload/credential（统一 envelope；request 已解包 data）。
 * COS 未配置时返回 configured=false（前端跳过直传，不伪造可用）。
 */
import type { UploadCredentialData, UploadScene } from '@/types/api'
import { request } from './request'

/** 申请 COS 直传临时凭证（STS；按场景限对象键前缀） */
export function getUploadCredential(scene: UploadScene, ext?: string) {
  return request<UploadCredentialData>('/api/upload/credential', {
    method: 'POST',
    data: ext ? { scene, ext } : { scene },
  })
}