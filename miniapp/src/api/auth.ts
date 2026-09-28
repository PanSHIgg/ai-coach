/**
 * auth API · 登录 / 当前用户（对齐 contracts/ts/api.d.ts）
 */
import type { LoginData, LoginRequest, UserDetail } from '@/types/api'
import { request } from './request'

/** 微信登录（code2session → JWT；Mock 态 code 任意值） */
export function login(data: LoginRequest) {
  return request<LoginData>('/api/auth/login', { method: 'POST', data, silent: true })
}

/** 当前用户信息（含权益） */
export function getMe() {
  return request<UserDetail>('/api/auth/me')
}
