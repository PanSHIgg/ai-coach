/**
 * task API · 任务中心 / 每日签到 / 积分（Wave B）
 *
 * 契约：contracts/openapi.yaml
 *   GET  /api/task/list       任务列表（含每日签到状态）
 *   POST /api/task/checkin    每日签到（当日幂等）
 *   GET  /api/points          积分概览（余额 / 累计获得 / 兑换门槛）
 *   GET  /api/points/list     积分明细分页
 */
import type {
  TaskListData,
  TaskCheckinData,
  PointsOverviewData,
  PointsPageData,
} from '@/types/api'
import { request } from './request'

/** 任务列表 */
export function getTaskList(): Promise<TaskListData> {
  return request<TaskListData>('/api/task/list')
}

/** 每日签到（当日重复签到 points_added=0） */
export function checkin(): Promise<TaskCheckinData> {
  return request<TaskCheckinData>('/api/task/checkin', { method: 'POST', data: {} })
}

/** 积分概览 */
export function getPoints(): Promise<PointsOverviewData> {
  return request<PointsOverviewData>('/api/points')
}

/** 积分明细分页（type：1获得 2消耗；缺省=全部） */
export function getPointsList(params?: {
  page?: number
  page_size?: number
  type?: number
}): Promise<PointsPageData> {
  return request<PointsPageData>('/api/points/list', { data: params })
}