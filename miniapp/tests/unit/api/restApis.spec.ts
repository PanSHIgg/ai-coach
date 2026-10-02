/**
 * api/task · api/privacy · api/report 薄封装层
 *
 * 这些函数只负责把「路径 / 方法 / 入参」转交 request()，并把 request 的结果原样返回
 * （envelope 解包发生在 request.ts，已有独立覆盖）。此处以参数化合并同类，仅断言
 * 每个函数对 request() 的调用契约与返回透传。
 */
import { describe, it, expect, vi } from 'vitest'
import { request } from '@/api/request'
import { getTaskList, checkin, getPoints, getPointsList } from '@/api/task'
import { getPrivacy, updatePrivacy, deleteAccount } from '@/api/privacy'
import { getWeeklyReport, exportReport, getExclusiveOffers } from '@/api/report'

vi.mock('@/api/request', () => ({ request: vi.fn() }))

const requestMock = vi.mocked(request)
/** request 的返回值原样透传哨兵 */
const SENTINEL = Symbol('request-result')

interface Case {
  name: string
  call: () => Promise<unknown>
  expected: unknown[]
}

const privacyPayload = { anonymous: false, mask_share: true }
const exportPayload = { report_type: 'weekly', format: 'csv' } as const
const pointsParams = { page: 2, page_size: 20, type: 1 }

const cases: Case[] = [
  { name: 'getTaskList → GET /api/task/list', call: () => getTaskList(), expected: ['/api/task/list'] },
  {
    name: 'checkin → POST /api/task/checkin',
    call: () => checkin(),
    expected: ['/api/task/checkin', { method: 'POST', data: {} }],
  },
  { name: 'getPoints → GET /api/points', call: () => getPoints(), expected: ['/api/points'] },
  {
    name: 'getPointsList → GET /api/points/list（带分页入参）',
    call: () => getPointsList(pointsParams),
    expected: ['/api/points/list', { data: pointsParams }],
  },
  { name: 'getPrivacy → GET /api/privacy', call: () => getPrivacy(), expected: ['/api/privacy'] },
  {
    name: 'updatePrivacy → PUT /api/privacy',
    call: () => updatePrivacy(privacyPayload),
    expected: ['/api/privacy', { method: 'PUT', data: privacyPayload }],
  },
  {
    name: 'deleteAccount → DELETE /api/account',
    call: () => deleteAccount(),
    expected: ['/api/account', { method: 'DELETE' }],
  },
  {
    name: 'getWeeklyReport（缺省周）→ GET /api/report/weekly',
    call: () => getWeeklyReport(),
    expected: ['/api/report/weekly'],
  },
  {
    name: 'getWeeklyReport（指定周）→ 附带 week 查询串',
    call: () => getWeeklyReport('2026-W40'),
    expected: ['/api/report/weekly?week=2026-W40'],
  },
  {
    name: 'exportReport → POST /api/report/export',
    call: () => exportReport(exportPayload),
    expected: ['/api/report/export', { method: 'POST', data: exportPayload }],
  },
  {
    name: 'getExclusiveOffers → GET /api/coupon/exclusive',
    call: () => getExclusiveOffers(),
    expected: ['/api/coupon/exclusive'],
  },
]

describe('api 薄封装 · request 调用契约与结果透传', () => {
  it.each(cases)('$name', async ({ call, expected }) => {
    requestMock.mockReset()
    requestMock.mockResolvedValue(SENTINEL)

    const promise = call()
    expect(requestMock).toHaveBeenCalledWith(...expected)
    await expect(promise).resolves.toBe(SENTINEL)
  })
})