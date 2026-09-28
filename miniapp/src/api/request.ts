/**
 * request.ts · uni.request 统一封装（P0-f）
 *
 * - baseURL 取 env.VITE_API_BASE（默认 http://localhost:9000，指向 contracts/mock/server.mjs）
 * - 自动附 `Authorization: Bearer <token>`（storage 读取）
 * - HTTP 401 或业务 code=1001：用 refresh_token 静默刷新一次并重放原请求；
 *   刷新失败清登录态并 reLaunch 到登录页
 *   【假设】刷新端点为 /api/auth/refresh（34 接口契约暂未包含，登录接口联调时对齐）
 * - 业务 code≠0：useToast 提示 message（silent 模式不弹），reject Error(message)
 * - 成功统一返回 envelope.data
 */
import type { Envelope } from '@/types/api'
import { useToast } from '@/composables/useToast'

export const BASE_URL: string = import.meta.env.VITE_API_BASE || 'http://localhost:9000'

const TOKEN_KEY = 'token'
const REFRESH_TOKEN_KEY = 'refresh_token'
/** 未登录/登录过期（contracts/ts/api.d.ts ErrorCode.UNAUTHORIZED） */
const CODE_UNAUTHORIZED = 1001

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE'
  data?: Record<string, unknown>
  /** 静默模式：失败不弹 toast（登录页、内部刷新等调用用） */
  silent?: boolean
  /** 内部标记：原请求已经历一次刷新重放，防止刷新死循环 */
  _retried?: boolean
}

/* ---------- 登录态存取 ---------- */

export function getToken(): string {
  return (uni.getStorageSync(TOKEN_KEY) as string) || ''
}

export function getRefreshToken(): string {
  return (uni.getStorageSync(REFRESH_TOKEN_KEY) as string) || ''
}

export function saveToken(token: string, refreshToken: string): void {
  uni.setStorageSync(TOKEN_KEY, token)
  uni.setStorageSync(REFRESH_TOKEN_KEY, refreshToken)
}

/** 清登录态（本地仅清 token，不主动跳转，跳转由调用方决定） */
export function clearAuth(): void {
  uni.removeStorageSync(TOKEN_KEY)
  uni.removeStorageSync(REFRESH_TOKEN_KEY)
}

function toLogin(): void {
  clearAuth()
  uni.reLaunch({ url: '/pages/login/login' })
}

/* ---------- 静默刷新（并发 401 只发一次） ---------- */

let refreshing: Promise<boolean> | null = null

function refreshOnce(): Promise<boolean> {
  if (!refreshing) {
    refreshing = doRefresh().finally(() => {
      refreshing = null
    })
  }
  return refreshing
}

function doRefresh(): Promise<boolean> {
  const refreshToken = getRefreshToken()
  if (!refreshToken) return Promise.resolve(false)
  return new Promise((resolve) => {
    uni.request({
      // 【假设】刷新端点 /api/auth/refresh；Mock 未实现该路由（404 envelope）→ 视为刷新失败走登录页
      url: `${BASE_URL}/api/auth/refresh`,
      method: 'POST',
      data: { refresh_token: refreshToken },
      success: (res) => {
        const env = res.data as Envelope<{ token: string; refresh_token: string }> | null
        if (res.statusCode === 200 && env && env.code === 0 && env.data) {
          saveToken(env.data.token, env.data.refresh_token)
          resolve(true)
        } else {
          resolve(false)
        }
      },
      fail: () => resolve(false),
    })
  })
}

/* ---------- 核心请求 ---------- */

export function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', data, silent = false, _retried = false } = options
  const token = getToken()

  return new Promise<T>((resolve, reject) => {
    uni.request({
      url: `${BASE_URL}${path}`,
      method,
      data,
      header: token ? { Authorization: `Bearer ${token}` } : {},
      success: (res) => {
        const env = res.data as Envelope<T> | null

        // HTTP 401 或业务 1001 → 静默刷新一次并重放；仍失败清态回登录页
        if (res.statusCode === 401 || (env && env.code === CODE_UNAUTHORIZED)) {
          if (_retried) {
            toLogin()
            reject(new Error('登录已过期，请重新登录'))
            return
          }
          refreshOnce().then((ok) => {
            if (ok) {
              request<T>(path, { ...options, _retried: true }).then(resolve, reject)
            } else {
              toLogin()
              reject(new Error('登录已过期，请重新登录'))
            }
          })
          return
        }

        // HTTP 层失败
        if (res.statusCode < 200 || res.statusCode >= 300) {
          const msg = (env && env.message) || `请求失败（${res.statusCode}）`
          if (!silent) useToast().error({ title: msg })
          reject(new Error(msg))
          return
        }

        // envelope 校验（非 JSON / 格式异常）
        if (!env || typeof env.code !== 'number') {
          const msg = '响应格式异常'
          if (!silent) useToast().error({ title: msg })
          reject(new Error(msg))
          return
        }

        // 业务失败：code≠0 → toast 错误信息
        if (env.code !== 0) {
          if (!silent) useToast().error({ title: env.message || '操作失败' })
          reject(new Error(env.message || '操作失败'))
          return
        }

        // 成功：统一返回 envelope.data
        resolve(env.data as T)
      },
      fail: (err) => {
        const msg = err.errMsg || '网络开小差了，请稍后重试'
        if (!silent) useToast().error({ title: msg })
        reject(new Error(msg))
      },
    })
  })
}
