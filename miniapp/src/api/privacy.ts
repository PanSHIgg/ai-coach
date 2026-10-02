/**
 * privacy API · 隐私控制 / 账号注销（Wave B）
 *
 * 契约：contracts/openapi.yaml
 *   GET    /api/privacy   读取隐私开关
 *   PUT    /api/privacy   更新隐私开关（部分字段）
 *   DELETE /api/account   账号注销（级联清除）——本页「一键删除」入口调用
 */
import type { PrivacyIn, PrivacyData, AccountDeleteData } from '@/types/api'
import { request } from './request'

/** 读取隐私设置 */
export function getPrivacy(): Promise<PrivacyData> {
  return request<PrivacyData>('/api/privacy')
}

/** 更新隐私设置（部分字段，返回更新后的完整设置） */
export function updatePrivacy(payload: PrivacyIn): Promise<PrivacyData> {
  return request<PrivacyData>('/api/privacy', { method: 'PUT', data: payload })
}

/**
 * 账号注销（DELETE /api/account）。
 * 后端由账户域实现；未就绪时调用失败会由 request 统一 toast，调用方据此降级提示。
 */
export function deleteAccount(): Promise<AccountDeleteData> {
  return request<AccountDeleteData>('/api/account', { method: 'DELETE' })
}