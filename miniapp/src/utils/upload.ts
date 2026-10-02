/**
 * upload.ts · 小程序直传 COS（COS 集成）
 *
 * 流程：POST /api/upload/credential 申请 STS 临时密钥 → COS SDK 直传 → 返回公开读 URL。
 * COS 未配置（configured=false）或上传失败 → 返回 null（调用方回退，不阻断主流程）。
 *
 * 条件编译：小程序端 cos-wx-sdk-v5（FilePath 直传），H5 端 cos-js-sdk-v5（Body: Blob）。
 */
import { getUploadCredential } from '@/api/upload'
import type { UploadCredentialData, UploadScene } from '@/types/api'

// #ifdef MP-WEIXIN
import COSWx from 'cos-wx-sdk-v5'
// #endif
// #ifdef H5
import COSJs from 'cos-js-sdk-v5'
// #endif

type UploadExt = 'jpg' | 'jpeg' | 'png' | 'webp'

/** COS SDK 最小调用面（屏蔽小程序/H5 两套 SDK 的构造签名差异） */
interface CosClient {
  putObject(
    params: Record<string, unknown>,
    callback: (err: Error | null, data: unknown) => void,
  ): void
}
type CosCtor = new (options: {
  getAuthorization: (options: unknown, callback: (data: unknown) => void) => void
}) => CosClient

/** 从临时路径推断扩展名（非白名单一律回落 jpg） */
function extOf(filePath: string): UploadExt {
  const m = /\.(\w+)(?:\?|$)/.exec(filePath)
  const ext = (m?.[1] || 'jpg').toLowerCase()
  return ext === 'jpeg' || ext === 'png' || ext === 'webp' ? ext : 'jpg'
}

/** SDK getAuthorization 回调 → 后端下发的 STS 临时密钥 */
function authOf(cred: UploadCredentialData) {
  const c = cred.credentials
  return () => ({
    TmpSecretId: c?.tmp_secret_id,
    TmpSecretKey: c?.tmp_secret_key,
    SecurityToken: c?.session_token,
    StartTime: c?.start_time,
    ExpiredTime: c?.expired_time,
  })
}

/** SDK 直传（平台分支由条件编译裁剪） */
function putToCos(cred: UploadCredentialData, filePath: string): Promise<void> {
  const base = { Bucket: cred.bucket, Region: cred.region, Key: cred.key }
  return new Promise((resolve, reject) => {
    // #ifdef MP-WEIXIN
    const cos = new (COSWx as unknown as CosCtor)({
      getAuthorization: (_o, cb) => cb(authOf(cred)()),
    })
    cos.putObject({ ...base, FilePath: filePath }, (err) => (err ? reject(err) : resolve()))
    // #endif
    // #ifdef H5
    fetch(filePath)
      .then((r) => r.blob())
      .then((blob) => {
        const cos = new (COSJs as unknown as CosCtor)({
          getAuthorization: (_o, cb) => cb(authOf(cred)()),
        })
        cos.putObject({ ...base, Body: blob }, (err) => (err ? reject(err) : resolve()))
      })
      .catch(reject)
    // #endif
  })
}

/**
 * 直传图片到 COS。
 *
 * @returns 公开读 URL；COS 未配置或上传失败返回 null（调用方回退，不抛错）。
 */
export async function uploadImage(filePath: string, scene: UploadScene): Promise<string | null> {
  if (!filePath) return null
  let cred: UploadCredentialData
  try {
    cred = await getUploadCredential(scene, extOf(filePath))
  } catch (e) {
    return null
  }
  if (!cred.configured || !cred.credentials) return null
  try {
    await putToCos(cred, filePath)
    return cred.public_url
  } catch (e) {
    return null
  }
}