/**
 * merchant API · 商家：列表（LBS）/ 详情 / 标准 SKU 目录 / 附近比价（FE4 · Phase 3）
 *
 * 契约：openapi.yaml
 *   GET /api/merchant/list     商家列表（lat/lng/radius/category/page/page_size）
 *   GET /api/merchant/{id}     商家详情（含在售 SKU）
 *   GET /api/sku/catalog       标准目录（category 可选）
 *   GET /api/merchant/compare  附近商家比价（按标准 SKU 目录 id）
 */
import type {
  MerchantPageData,
  MerchantDetail,
  CatalogData,
  MerchantCompareData,
} from '@/types/api'
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

export interface MerchantCompareParams {
  /** 标准 SKU 目录 id（CatalogItem.id） */
  sku_id: number
  /** 用户纬度，缺省时后端按默认城市返回 */
  lat?: number
  /** 用户经度，缺省时后端按默认城市返回 */
  lng?: number
}

/** 附近商家比价（在售该 SKU 的商家，含券后抵扣，按价格升序） */
export function getMerchantCompare(params: MerchantCompareParams) {
  return request<MerchantCompareData>('/api/merchant/compare', { data: params })
}
