/**
 * order API · 订单 / 支付 / 核销 / 券（FE4 · Phase 3）
 *
 * 契约：openapi.yaml
 *   POST /api/order               创建订单（金额服务端重算）
 *   POST /api/order/{id}/pay      微信支付预下单
 *   POST /api/order/{id}/redeem   核销（核销码唯一）
 *   GET  /api/order/list          我的订单（status 可选）
 *   GET  /api/coupon/list         我的券（status 可选）
 */
import type {
  OrderCreateIn,
  OrderCreatedData,
  PayData,
  OrderPageData,
  CouponPageData,
  RedeemIn,
  RedeemData,
} from '@/types/api'
import { request } from './request'

/** 创建订单（返回 order_id / 金额 / 支付截止时间） */
export function createOrder(data: OrderCreateIn) {
  return request<OrderCreatedData>('/api/order', { method: 'POST', data })
}

/** 支付预下单（返回 pay_params 拉起微信支付） */
export function payOrder(id: number) {
  return request<PayData>(`/api/order/${id}/pay`, { method: 'POST', data: {} })
}

/** 我的订单分页（status：1待支付 2待核销 3已完成 4已取消 5已退款） */
export function getOrders(params?: {
  status?: 1 | 2 | 3 | 4 | 5
  page?: number
  page_size?: number
}) {
  return request<OrderPageData>('/api/order/list', { data: params })
}

/** 我的券分页（status：1未用 2已用 3过期 4作废） */
export function getCoupons(params?: {
  status?: 1 | 2 | 3 | 4
  page?: number
  page_size?: number
}) {
  return request<CouponPageData>('/api/coupon/list', { data: params })
}

/** 核销（商家侧扫码；用户侧仅展示核销码，此处按契约封装备用） */
export function redeemOrder(id: number, data: RedeemIn) {
  return request<RedeemData>(`/api/order/${id}/redeem`, { method: 'POST', data })
}
