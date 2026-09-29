/**
 * merchant API · 商家：列表（LBS）/ 详情 / 标准 SKU 目录（FE4 · Phase 3）
 *
 * 契约：openapi.yaml
 *   GET /api/merchant/list    商家列表（lat/lng/radius/category/page/page_size）
 *   GET /api/merchant/{id}    商家详情（含在售 SKU）
 *   GET /api/sku/catalog      标准目录（category 可选）
 */
import type { MerchantPageData, MerchantDetail, CatalogData } from '@/types/api'
import { request } from './request'

export interface MerchantListParams {
  lat?: number
  lng?: number
  /** 搜索半径（米），默认 3000 */
  radius?: number
  /** 类目筛选：轻食 / 健身房 等 */
  category?: string
  page?: number
  page_size?: number
}

/** 商家列表（按距离升序；不传经纬度时后端按默认城市返回） */
export function getMerchants(params?: MerchantListParams) {
  return request<MerchantPageData>('/api/merchant/list', { data: params })
}

/** 商家详情（含在售 SKU） */
export function getMerchantDetail(id: number) {
  return request<MerchantDetail>(`/api/merchant/${id}`)
}

/** 标准 SKU 目录（平台统一建品 + 限价区间） */
export function getSkuCatalog(params?: { category?: string }) {
  return request<CatalogData>('/api/sku/catalog', { data: params })
}
