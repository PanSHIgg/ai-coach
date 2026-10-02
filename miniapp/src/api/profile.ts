/**
 * profile API · 身体档案（P1 FE1 建档页使用）+ 头像更新（COS 集成）
 */
import type { BodyProfileIn, BodyProfileOut, UserDetail } from '@/types/api'
import { request } from './request'

/** 获取身体档案（未建档时后端返回 data=null，非错误） */
export function getBodyProfile() {
  return request<BodyProfileOut | null>('/api/body-profile')
}

/** 保存身体档案（后端算 BMR / target_calories） */
export function saveBodyProfile(data: BodyProfileIn) {
  return request<BodyProfileOut>('/api/body-profile', { method: 'POST', data })
}

/** 更新头像（COS 直传成功后回填公开读 URL）；返回更新后的当前用户详情 */
export function updateAvatar(avatar_url: string) {
  return request<UserDetail>('/api/user/avatar', { method: 'POST', data: { avatar_url } })
}
