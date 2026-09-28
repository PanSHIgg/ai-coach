/**
 * profile API · 身体档案（P1 FE1 建档页使用）
 */
import type { BodyProfileIn, BodyProfileOut } from '@/types/api'
import { request } from './request'

/** 获取身体档案 */
export function getBodyProfile() {
  return request<BodyProfileOut>('/api/body-profile')
}

/** 保存身体档案（后端算 BMR / target_calories） */
export function saveBodyProfile(data: BodyProfileIn) {
  return request<BodyProfileOut>('/api/body-profile', { method: 'POST', data })
}
