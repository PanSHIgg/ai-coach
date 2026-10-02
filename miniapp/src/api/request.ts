/**
 * request.ts · uni.request 统一封装（P0-f）
 *
 * - baseURL 只取 env.VITE_API_BASE（无内置默认值：缺省=空串=H5 同源；小程序端空串启动即抛错）
 * - 自动附 `Authorization: Bearer <token>`（storage 读取）
 * - HTTP 401 或业务 code=1001：用 refresh_token 静默刷新一次并重放原请求；
 *   刷新失败清登录态并 reLaunch 到登录页
 *   【假设】刷新端点为 /api/auth/refresh（契约与 Mock 均已实现 /api/auth/refresh）
 * - 业务 code≠0：useToast 提示 message（silent 模式不弹），reject Error(message)
 * - 成功统一返回 envelope.data
 */
import type { Envelope } from '@/types/api'
import { useToast } from '@/composables/useToast'
import { redirectToLogin } from '@/utils/nav'

// 基址：只由 .env.[mode] 的 VITE_API_BASE 注入（开发 http://localhost = 本机 nginx 反代 /api；
// 生产 H5 显式留空走同源、小程序必须填绝对域名），代码内不再内置任何地址默认值。
// 兜底空串 = 「同源」语义：H5 成立；小程序端交给下方 #ifdef MP-WEIXIN 断言拦成启动即报错。
// 用 ?? 而非 ||：允许显式留空（H5 同源部署，由 nginx 反代 /api），空串不再被 fallback 覆盖。
export const BASE_URL: string = import.meta.env.VITE_API_BASE ?? ''

// #ifdef MP-WEIXIN
// 小程序不支持相对 URL：BASE_URL 为空时每个请求都会在网络层静默失败（表现为"零请求零报错"），
// 而 .env.production 的留空只对 H5 同源反代成立，因此小程序侧必须启动即报错而不是静默。
// MODE !== 'test'：vitest 不做 uni 条件编译，#ifdef 块在单测里同样会执行；
// 若不排除 test，任何未设 VITE_API_BASE 的环境（含干净 clone）都会让整套单测在导入期即抛。
if (!BASE_URL && import.meta.env.MODE !== 'test') {
  throw new Error(
    '[request] 小程序端 VITE_API_BASE 不能为空，请填绝对域名（仅 H5 可留空走 nginx 同源反代）',
  )
}
// #endif

const TOKEN_KEY = 'token'
const REFRESH_TOKEN_KEY = 'refresh_token'
/** 未登录/登录过期（contracts/ts/api.d.ts ErrorCode.UNAUTHORIZED） */
const CODE_UNAUTHORIZED = 1001

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE'
  /** 请求体：对象即可（各 API 入参接口无需显式索引签名） */
  data?: object
  /** 静默模式：失败不弹 toast（登录页、内部刷新等调用用） */
  silent?: boolean
  /** 内部标记：原请求已经历一次刷新重放，防止刷新死循环 */
  _retried?: boolean
}

/* ---------- 离线入队钩子（F-03，由 utils/offline 注册，解耦避免循环依赖） ---------- */

/**
 * 网络类失败时的入队钩子签名：命中关键写操作白名单且新入队返回 true。
 * 由 utils/offline 在模块加载时注册；未注册时行为与改造前完全一致。
 */
type NetworkFailHook = (
  path: string,
  method: 'GET' | 'POST' | 'PUT' | 'DELETE',
  data?: object,
) => boolean

let networkFailHook: NetworkFailHook | null = null

/** 注册网络失败入队钩子（仅 utils/offline 调用） */
export function setNetworkFailHook(hook: NetworkFailHook): void {
  networkFailHook = hook
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
  // 携带 redirect 回跳原页（§3.3/§13.2）
  redirectToLogin()
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
      // 刷新端点 /api/auth/refresh（契约与 Mock 均已实现 /api/auth/refresh）
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

        // 业务失败：code≠0 → toast 错误信息（Error 附带 code，供调用方按错误码分支，如 4102 防刷）
        if (env.code !== 0) {
          const msg = env.message || '操作失败'
          if (!silent) useToast().error({ title: msg })
          reject(Object.assign(new Error(msg), { code: env.code }))
          return
        }

        // 成功：统一返回 envelope.data
        resolve(env.data as T)
      },
      fail: (err) => {
        const msg = err.errMsg || '网络开小差了，请稍后重试'
        // F-03：关键写操作网络失败 → 走离线入队钩子（仅网络类失败；4xx/业务错走 success 分支，不受影响）
        // 新入队时由 offline 弹出「离线暂存」提示，此处不再重复弹通用网络错 toast
        const queued = networkFailHook ? networkFailHook(path, method, data) : false
        if (!silent && !queued) useToast().error({ title: msg })
        reject(new Error(msg))
      },
    })
  })
}
