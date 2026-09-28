/**
 * weight API · 体重记录与趋势（FE-w）
 *
 * 契约：openapi.yaml `/api/weight*`（BE-w）
 *   GET  /api/weight/list     分页列表（record_at DESC）
 *   POST /api/weight          新增记录
 *   DELETE /api/weight/{id}   删除记录
 *   GET  /api/weight/trend    趋势折线点（缺省最近 30 天，按 record_at 升序）
 */
import type {
  WeightRecordIn,
  WeightRecordOut,
  WeightPageData,
  WeightDeleteData,
  WeightTrendData,
} from '@/types/api'
import { request } from './request'

/** 新增体重记录（weight 单位 kg） */
export function createWeight(data: WeightRecordIn) {
  return request<WeightRecordOut>('/api/weight', { method: 'POST', data })
}

/** 体重记录分页列表 */
export function listWeight(params?: { page?: number; page_size?: number }) {
  return request<WeightPageData>('/api/weight/list', { data: params })
}

/** 删除体重记录 */
export function deleteWeight(id: number) {
  return request<WeightDeleteData>(`/api/weight/${id}`, { method: 'DELETE' })
}

/** 体重趋势（start_date / end_date 格式 YYYY-MM-DD，缺省后端取最近 30 天） */
export function getWeightTrend(params?: { start_date?: string; end_date?: string }) {
  return request<WeightTrendData>('/api/weight/trend', { data: params })
}