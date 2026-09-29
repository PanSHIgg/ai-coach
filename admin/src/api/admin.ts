import { client, unwrap } from './client'
import type {
  AdminAuditIn,
  AdminCouponPoolIn,
  AdminCouponPoolOut,
  AdminCouponPoolPageData,
  AdminGrantData,
  AdminGrantIn,
  AdminLoginData,
  AdminLoginIn,
  AdminMerchantPageData,
  AdminMerchantSkuData,
  AdminMerchantSkuIn,
  CatalogData,
  DashboardData,
  OrderPageData,
} from '@/types/api'

/** 管理员登录 POST /api/admin/login */
export function adminLogin(data: AdminLoginIn): Promise<AdminLoginData> {
  return unwrap(client.post('/admin/login', data))
}

/** 运营看板 GET /api/admin/dashboard */
export function getDashboard(date?: string): Promise<DashboardData> {
  return unwrap(client.get('/admin/dashboard', { params: date ? { date } : {} }))
}

/** 商家列表 GET /api/admin/merchants */
export function listMerchants(params: {
  audit_status?: number
  page?: number
  page_size?: number
}): Promise<AdminMerchantPageData> {
  return unwrap(client.get('/admin/merchants', { params }))
}

/** 商家入驻审核 POST /api/admin/merchants/{id}/audit */
export function auditMerchant(id: number, data: AdminAuditIn): Promise<unknown> {
  return unwrap(client.post(`/admin/merchants/${id}/audit`, data))
}

/** 标准目录 GET /api/admin/sku-catalog（管理侧；category 可选） */
export function getSkuCatalog(category?: string): Promise<CatalogData> {
  return unwrap(client.get('/admin/sku-catalog', { params: category ? { category } : {} }))
}

/** 商家选品定价 POST /api/admin/merchant-skus */
export function upsertMerchantSku(data: AdminMerchantSkuIn): Promise<AdminMerchantSkuData> {
  return unwrap(client.post('/admin/merchant-skus', data))
}

/** 券池列表 GET /api/admin/coupon-pools */
export function listCouponPools(params: {
  page?: number
  page_size?: number
}): Promise<AdminCouponPoolPageData> {
  return unwrap(client.get('/admin/coupon-pools', { params }))
}

/** 创建券池 POST /api/admin/coupon-pools */
export function createCouponPool(data: AdminCouponPoolIn): Promise<AdminCouponPoolOut> {
  return unwrap(client.post('/admin/coupon-pools', data))
}

/** 券池发放 POST /api/admin/coupon-pools/{id}/grant */
export function grantCoupon(data: AdminGrantIn): Promise<AdminGrantData> {
  return unwrap(client.post(`/admin/coupon-pools/${data.pool_id}/grant`, data))
}

/** 订单监控 GET /api/admin/orders */
export function listOrders(params: {
  status?: number
  merchant_id?: number
  page?: number
  page_size?: number
}): Promise<OrderPageData> {
  return unwrap(client.get('/admin/orders', { params }))
}
