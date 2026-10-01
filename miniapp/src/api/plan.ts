/**
 * plan API · 平台自营会员订阅付费（G2）
 *
 * 契约：contracts/openapi.yaml（类型见 src/types/api.d.ts）
 *   GET  /api/plan/list            会员档位与价格（服务端唯一真源）
 *   GET  /api/plan/benefit         当前用户会员权益（tier / 次数 / 有效期）
 *   POST /api/plan/order           创建订阅订单（只传 tier，金额服务端重算，15 分钟过期）
 *   POST /api/plan/order/{id}/pay  支付（PAY_MOCK_MODE 下 pay_params 为空对象 {}）
 *   GET  /api/plan/orders          我的会员订单
 *
 * 注：刻意避开 /api/subscription（实为「提醒订阅」，notification 域）。
 */
import type {
  PlanListData,
  PlanBenefitData,
  PlanOrderIn,
  PlanOrderData,
  PlanPayData,
  PlanOrderPageData,
} from '@/types/api'
import { request } from './request'

/** 档位与价格（tier：1进阶 2高级 3终身） */
export function getPlans() {
  return request<PlanListData>('/api/plan/list')
}

/** 当前权益：tier 0基础 1进阶 2高级 3终身 + 剩余次数 + 有效期 */
export function getPlanBenefit() {
  return request<PlanBenefitData>('/api/plan/benefit')
}

/** 下单（金额服务端按 tier 重算，前端不传金额） */
export function createPlanOrder(data: PlanOrderIn) {
  return request<PlanOrderData>('/api/plan/order', { method: 'POST', data })
}

/** 支付（mock 模式直接推进已支付；否则返回微信拉起参数） */
export function payPlanOrder(id: number) {
  return request<PlanPayData>(`/api/plan/order/${id}/pay`, { method: 'POST', data: {} })
}

/** 我的会员订单分页（status：1待支付 2已支付 3已取消） */
export function getPlanOrders(params?: {
  status?: 1 | 2 | 3
  page?: number
  page_size?: number
}) {
  return request<PlanOrderPageData>('/api/plan/orders', { data: params })
}
