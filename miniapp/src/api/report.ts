/**
 * report API · 报告导出 / 周报 / 专属优惠（Wave B）
 *
 * 契约：contracts/openapi.yaml
 *   GET  /api/report/weekly      热量控制周报（缺口/步数/体重趋势 + AI 点评）
 *   POST /api/report/export      报告导出（csv 文本）
 *   GET  /api/coupon/exclusive   专属优惠（异业联盟券目录）
 */
import type {
  WeeklyReportData,
  ReportExportIn,
  ReportExportData,
  ExclusiveCouponData,
} from '@/types/api'
import { request } from './request'

/** 热量控制周报（week 缺省=本周，格式 YYYY-Www） */
export function getWeeklyReport(week?: string): Promise<WeeklyReportData> {
  const qs = week ? `?week=${encodeURIComponent(week)}` : ''
  return request<WeeklyReportData>(`/api/report/weekly${qs}`)
}

/** 报告导出（返回 filename/mime/content，落地保存由前端处理） */
export function exportReport(payload: ReportExportIn): Promise<ReportExportData> {
  return request<ReportExportData>('/api/report/export', { method: 'POST', data: payload })
}

/** 专属优惠（异业券） */
export function getExclusiveOffers(): Promise<ExclusiveCouponData> {
  return request<ExclusiveCouponData>('/api/coupon/exclusive')
}