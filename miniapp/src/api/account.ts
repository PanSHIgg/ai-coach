/**
 * account API · 热量账户（今日 / 趋势）
 */
import type { DailyAccount, AccountTrendData, TodayStatusIn } from '@/types/api'
import { useToast } from '@/composables/useToast'
import { request } from './request'

/** 资源不存在（types/api.d.ts ErrorCode.NOT_FOUND=3001；后端映射 HTTP 404） */
const CODE_NOT_FOUND = 3001
/**
 * 未建档的唯一判据文案：backend/app/services/account.py 在「无档案行」与「体重<=0」时
 * 抛 AppException(NOT_FOUND, "尚未创建身体档案") → HTTP 404 + code 3001 + 该 message
 * （见 backend/tests/test_account_api.py）。request.ts 把它透传成 Error.message。
 * 【假设】后端改文案则此处失配 → 退回「照旧 toast」：宁可多提示一次，也不吞掉真故障。
 */
const NO_PROFILE_MSG = '尚未创建身体档案'

/**
 * 是否为「预期内的未建档 404」。
 * 只认这两条：未建档原文文案 / 业务码 3001。网络故障（request:fail、网络开小差了）、
 * 5xx（请求失败（500）/ 服务器错误文案）、404 但非该文案（如路由/反代配错 → 「资源不存在」）、
 * 响应格式异常 全部落回 false → 照旧提示，故不会掩盖真故障。
 */
function isNoProfileError(err: unknown): boolean {
  const e = err as (Error & { code?: number }) | null | undefined
  if (!e) return false
  if (typeof e.message === 'string' && e.message.includes(NO_PROFILE_MSG)) return true
  // HTTP 200 + envelope code≠0 时 request.ts 才挂 code（当前链路走 404，此为同义兜底）
  return e.code === CODE_NOT_FOUND
}

/** 未登录 / 登录过期（types/api.d.ts ErrorCode.UNAUTHORIZED=1001，HTTP 401 同义） */
const CODE_UNAUTHORIZED = 1001
/**
 * request.ts 的 401 分支固定文案：该分支自己负责 clearAuth + reLaunch 到登录页，
 * silent 模式下**不弹** toast（改造前也是静默的）。这里静默它，否则首页/eat 页会在
 * 「跳登录页」的同时多弹一次「登录已过期」，把别的提示顶掉（uni.showToast 是单例）。
 * 只认这一条文案 + code 1001，真网络故障（request:fail / 5xx / 响应格式异常）不在其列。
 */
const AUTH_EXPIRED_MSG = '登录已过期，请重新登录'

function isAuthExpiredError(err: unknown): boolean {
  const e = err as (Error & { code?: number }) | null | undefined
  if (!e) return false
  if (typeof e.message === 'string' && e.message.includes(AUTH_EXPIRED_MSG)) return true
  return e.code === CODE_UNAUTHORIZED
}

/**
 * 今日热量账户。
 * silent 收口：request 层不弹 toast，由此处按判据决定——「未建档」与「登录过期」静默
 * （前者交由首页建档引导卡承接 §5.1，后者由 request 层跳登录页），其余失败在此原样补一次
 * error toast，行为与改造前一致。失败仍然 reject，accountStore 的 error 标记与页面错误态不受影响。
 */
export function getToday() {
  return request<DailyAccount>('/api/account/today', { silent: true }).catch((err: unknown) => {
    if (!isNoProfileError(err) && !isAuthExpiredError(err)) {
      const msg = err instanceof Error ? err.message : String(err ?? '')
      useToast().error({ title: msg || '请求失败' })
    }
    throw err
  })
}

/** 写入当日状态（F-01，§2.3.1 五选一）；返回重算后的今日账户 */
export function setTodayStatus(activity_level: TodayStatusIn['activity_level']) {
  return request<DailyAccount>('/api/account/today-status', {
    method: 'POST',
    data: { activity_level },
  })
}

/** 近 N 天趋势（默认 7 天；契约参数为 start_date/end_date，格式 YYYY-MM-DD） */
export function getTrend(days = 7) {
  const end = new Date()
  const start = new Date(end)
  start.setDate(start.getDate() - (days - 1))
  // 本地时区日期（toISOString 为 UTC，UTC+8 凌晨会把 end_date 错切到昨天）
  const fmt = (d: Date) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  return request<AccountTrendData>(
    `/api/account/trend?start_date=${fmt(start)}&end_date=${fmt(end)}`,
  )
}
