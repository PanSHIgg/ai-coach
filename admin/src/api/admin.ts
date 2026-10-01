import { client, unwrap } from './client'
import type {
  AdminAuditIn,
  AdminAuditPageData,
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
  AdminReviewData,
  AdminReviewIn,
  AdminSkuCatalogIn,
  CatalogData,
  CatalogItem,
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

/** 新建标准目录项 POST /api/admin/sku-catalog（平台运营维护；重名 2001/422） */
export function createSkuCatalog(data: AdminSkuCatalogIn): Promise<CatalogItem> {
  return unwrap(client.post('/admin/sku-catalog', data))
}

/** 编辑标准目录项 PUT /api/admin/sku-catalog/{id}（平台运营维护；不存在 3001/404） */
export function updateSkuCatalog(id: number, data: AdminSkuCatalogIn): Promise<CatalogItem> {
  return unwrap(client.put(`/admin/sku-catalog/${id}`, data))
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

/** 内容审核队列 GET /api/admin/audit/list */
export function listAudit(params: {
  status?: number
  page?: number
  page_size?: number
}): Promise<AdminAuditPageData> {
  return unwrap(client.get('/admin/audit/list', { params }))
}

/** 处理审核 POST /api/admin/audit/{id}/review */
export function reviewAudit(id: number, data: AdminReviewIn): Promise<AdminReviewData> {
  return unwrap(client.post(`/admin/audit/${id}/review`, data))
}
