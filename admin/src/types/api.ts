/**
 * 契约类型：手写自 contracts/openapi.yaml
 * （Envelope / PageMeta / DashboardData / Admin* 组件 schema / CatalogItem / OrderBrief）
 */

/** 统一响应 envelope（contracts/openapi.yaml:1813） */
export interface Envelope<T = unknown> {
  code: number
  message: string
  data?: T
  request_id?: string
  errors?: Record<string, unknown>
}

/** 分页元信息（contracts/openapi.yaml:1831） */
export interface PageMeta {
  page: number
  page_size: number
  total: number
}

/** 1满减 2折扣 3免费 4体验 */
export type CouponType = 1 | 2 | 3 | 4
/** 1吃 2动 3异业 4通用 */
export type CouponScope = 1 | 2 | 3 | 4
/** 1待支付 2已支付待核销 3已完成 4已取消 5已退款 */
export type OrderStatus = 1 | 2 | 3 | 4 | 5
/** 1未用 2已用 3过期 4作废 */
export type CouponStatus = 1 | 2 | 3 | 4

/** 管理角色：1超管 2运营 3商家 */
export type AdminRole = 1 | 2 | 3

/** 运营看板（contracts/openapi.yaml:2481） */
export interface DashboardData {
  date: string
  user_count: number
  active_users_today: number
  meal_records_today: number
  orders_today: number
  gmv_today: number
  ai_calls_today: number
}

/** 管理员登录入参（contracts/openapi.yaml:2493） */
export interface AdminLoginIn {
  username: string
  password: string
}

/** 管理员登录返回（contracts/openapi.yaml:2499） */
export interface AdminLoginData {
  token: string
  role: AdminRole
  merchant_id: number | null
  username: string
}

/** 管理侧商家完整视图（contracts/openapi.yaml:2507） */
export interface AdminMerchantOut {
  id: number
  name: string
  category: string
  address: string
  phone: string | null
  lat: number | null
  lng: number | null
  rating: number
  cover_url: string | null
  status: number
  /** 0待审 1通过 2驳回 */
  audit_status: 0 | 1 | 2
  audit_reason: string | null
  owner_user_id: number | null
  created_at: string
}

export interface AdminMerchantPageData {
  items: AdminMerchantOut[]
  page: PageMeta
}

/** 商家入驻审核入参（contracts/openapi.yaml:2536） */
export interface AdminAuditIn {
  audit_status: 1 | 2
  reason?: string | null
}

/** 商家选品定价入参（contracts/openapi.yaml:2542） */
export interface AdminMerchantSkuIn {
  merchant_id: number
  catalog_id: number
  price: number
  stock?: number
  status?: 0 | 1
}

/** 商家 SKU 返回（contracts/openapi.yaml:2552） */
export interface AdminMerchantSkuData {
  id: number
  merchant_id: number
  merchant_name: string | null
  catalog_id: number
  catalog_code: string
  catalog_name: string
  price: number
  min_price: number
  max_price: number
  stock: number
  status: number
  updated_at: string | null
}

/** 商家 SKU 上下架入参（contracts/openapi.yaml:2568） */
export interface AdminSkuStatusIn {
  status: 0 | 1
}

/** 标准 SKU 目录项（contracts/openapi.yaml:2253） */
export interface CatalogItem {
  id: number
  code: string
  name: string
  category: string | null
  calories_low: number | null
  calories_high: number | null
  base_price: number
  min_price: number
  max_price: number
  unit: string | null
}

export interface CatalogData {
  items: CatalogItem[]
}

/** 创建券池入参（contracts/openapi.yaml:2573） */
export interface AdminCouponPoolIn {
  name: string
  type: CouponType
  scope: CouponScope
  amount?: number
  discount_rate?: number | null
  min_spend?: number
  merchant_id?: number | null
  total_count: number
  valid_from?: string | null
  valid_to?: string | null
}

/** 券池返回（contracts/openapi.yaml:2587） */
export interface AdminCouponPoolOut {
  id: number
  name: string
  type: CouponType
  scope: CouponScope
  amount: number
  discount_rate: number | null
  min_spend: number
  merchant_id: number | null
  total_count: number
  granted_count: number
  valid_from: string | null
  valid_to: string | null
  created_at: string
}

export interface AdminCouponPoolPageData {
  items: AdminCouponPoolOut[]
  page: PageMeta
}

/** 券池发放入参（contracts/openapi.yaml:2614） */
export interface AdminGrantIn {
  pool_id: number
  user_id: number
  count?: number
}

/** 用户券（contracts/openapi.yaml:2349） */
export interface CouponOut {
  id: number
  code: string
  type: CouponType
  scope: CouponScope
  amount: number
  discount_rate: number | null
  min_spend: number
  merchant_id: number | null
  status: CouponStatus
  valid_from: string | null
  valid_to: string | null
}

/** 券池发放返回（contracts/openapi.yaml:2621） */
export interface AdminGrantData {
  granted_count: number
  pool_id?: number
  user_id?: number
  coupons: CouponOut[]
}

/** 订单简要（contracts/openapi.yaml:2324） */
export interface OrderBrief {
  id: number
  order_no: string
  merchant_id: number
  merchant_name: string | null
  total_amount: number
  discount_amount: number
  pay_amount: number
  status: OrderStatus
  redeem_code: string | null
  expire_at: string | null
  created_at: string
}

export interface OrderPageData {
  items: OrderBrief[]
  page: PageMeta
}
