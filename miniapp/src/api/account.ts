/**
 * account API · 热量账户（今日 / 趋势）
 */
import type { DailyAccount, AccountTrendData, TodayStatusIn } from '@/types/api'
import { request } from './request'

/** 今日热量账户 */
export function getToday() {
  return request<DailyAccount>('/api/account/today')
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
