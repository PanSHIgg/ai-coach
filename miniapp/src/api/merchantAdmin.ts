/**
 * merchantAdmin.ts · 商家自助 API 封装（独立商家 token 域，FE4 · G11）
 *
 * 契约：openapi.yaml「商家自助」标签（security: MerchantBearer，独立于用户 JWT）
 *   POST /api/merchant/login            账号密码登录 → 换发商家 token
 *   GET  /api/merchant/me               当前商家信息
 *   GET  /api/merchant/skus             商家选品/定价列表
 *   PUT  /api/merchant/skus             批量在区间内定价
 *   POST /api/merchant/sku/{id}/toggle  上架/下架
 *   GET  /api/merchant/orders           商家订单/核销列表（status/page/page_size）
 *   POST /api/merchant/order/{id}/redeem 商家核销
 *   GET  /api/merchant/stats            商家数据看板
 *
 * token 注入说明（关键）：
 *   `@/api/request` 的 request() 固定注入用户 token（storage key 'token'）且
 *   RequestOptions 不接受自定义 header，无法承载 MerchantBearer；按任务约束
 *   「不改 request.ts」，本模块内自建等价的 merchantRequest（复用 request.ts
 *   导出的 BASE_URL），从独立 storage key 'merchant_token' 读取商家 token 并注入
 *   `Authorization: Bearer <merchant_token>`。商家域 401/1001 不做用户态静默刷新。
 */
import type {
  Envelope,
  MerchantLoginIn,
  MerchantLoginData,
  MerchantMeData,
  MerchantSkuListData,
  MerchantSkuPriceIn,
  MerchantSkuToggleData,
  MerchantOrderPageData,
  MerchantRedeemData,
  MerchantStatsData,
} from '@/types/api'
import { BASE_URL } from './request'
import { useToast } from '@/composables/useToast'

/**
 * 错误码常量：types/api.d.ts 的 ErrorCode 为类型声明（非运行时可解析模块），
 * 按 request.ts 既有约定硬编码（见 request.ts CODE_UNAUTHORIZED）。
 */
const CODE_OK = 0
const CODE_UNAUTHORIZED = 1001

/** 商家 token 独立存储 key（严禁与用户 token 'token' 混用） */
export const MERCHANT_TOKEN_KEY = 'merchant_token'

export function getMerchantToken(): string {
  return (uni.getStorageSync(MERCHANT_TOKEN_KEY) as string) || ''
}

export function saveMerchantToken(token: string): void {
  uni.setStorageSync(MERCHANT_TOKEN_KEY, token)
}

export function clearMerchantToken(): void {
  uni.removeStorageSync(MERCHANT_TOKEN_KEY)
}

export interface MerchantRequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE'
  data?: object
  /** 静默模式：失败不弹 toast，由调用方自行处理文案 */
  silent?: boolean
}

/** 商家域请求：等价 request()，但注入商家 token，且 401/1001 不做用户态刷新 */
function merchantRequest<T>(path: string, options: MerchantRequestOptions = {}): Promise<T> {
  const { method = 'GET', data, silent = false } = options
  const token = getMerchantToken()

  return new Promise<T>((resolve, reject) => {
    uni.request({
      url: `${BASE_URL}${path}`,
      method,
      data,
      header: token ? { Authorization: `Bearer ${token}` } : {},
      success: (res) => {
        const env = res.data as Envelope<T> | null

        // 商家域未认证：直接上抛 code=1001，交由页面清 token 回登录页（不动用户登录态）
        if (res.statusCode === 401 || (env && env.code === CODE_UNAUTHORIZED)) {
          const err = Object.assign(new Error('商家登录已过期，请重新登录'), {
            code: CODE_UNAUTHORIZED,
          })
          if (!silent) useToast().error({ title: err.message })
          reject(err)
          return
        }

        // HTTP 层失败
        if (res.statusCode < 200 || res.statusCode >= 300) {
          const msg = (env && env.message) || `请求失败（${res.statusCode}）`
          if (!silent) useToast().error({ title: msg })
          reject(new Error(msg))
          return
        }

        // envelope 校验
        if (!env || typeof env.code !== 'number') {
          const msg = '响应格式异常'
          if (!silent) useToast().error({ title: msg })
          reject(new Error(msg))
          return
        }

        // 业务失败：Error 附带 code，供调用方按错误码分支（如 2001 越界 / 5004 已核销）
        if (env.code !== CODE_OK) {
          const msg = env.message || '操作失败'
          if (!silent) useToast().error({ title: msg })
          reject(Object.assign(new Error(msg), { code: env.code }))
          return
        }

        resolve(env.data as T)
      },
      fail: (err) => {
        const msg = err.errMsg || '网络开小差了，请稍后重试'
        if (!silent) useToast().error({ title: msg })
        reject(new Error(msg))
      },
    })
  })
}

/** 商家账号密码登录（成功返回 MerchantBearer token） */
export function merchantLogin(input: MerchantLoginIn, silent = false): Promise<MerchantLoginData> {
  return merchantRequest<MerchantLoginData>('/api/merchant/login', {
    method: 'POST',
    data: input,
    silent,
  })
}

/** 当前商家信息 */
export function getMerchantMe(silent = false): Promise<MerchantMeData> {
  return merchantRequest<MerchantMeData>('/api/merchant/me', { silent })
}

/** 商家选品/定价列表（含目录限价区间回显） */
export function getMerchantSkus(silent = false): Promise<MerchantSkuListData> {
  return merchantRequest<MerchantSkuListData>('/api/merchant/skus', { silent })
}

/** 批量定价（越出目录区间后端返回 code=2001） */
export function updateMerchantSkus(
  items: MerchantSkuPriceIn[],
  silent = false,
): Promise<MerchantSkuListData> {
  return merchantRequest<MerchantSkuListData>('/api/merchant/skus', {
    method: 'PUT',
    data: { items },
    silent,
  })
}

/** 上架/下架切换 */
export function toggleMerchantSku(id: number, silent = false): Promise<MerchantSkuToggleData> {
  return merchantRequest<MerchantSkuToggleData>(`/api/merchant/sku/${id}/toggle`, {
    method: 'POST',
    silent,
  })
}

export interface MerchantOrderParams {
  /** 订单状态过滤：1待支付 2已支付待核销 3已完成 4已取消 5已退款 */
  status?: number
  page?: number
  page_size?: number
}

/** 商家订单/核销列表（分页） */
export function getMerchantOrders(
  params?: MerchantOrderParams,
  silent = false,
): Promise<MerchantOrderPageData> {
  return merchantRequest<MerchantOrderPageData>('/api/merchant/orders', { data: params, silent })
}

/** 商家核销（重复核销后端返回 code=5004） */
export function redeemMerchantOrder(id: number, silent = false): Promise<MerchantRedeemData> {
  return merchantRequest<MerchantRedeemData>(`/api/merchant/order/${id}/redeem`, {
    method: 'POST',
    silent,
  })
}

/** 商家数据看板 */
export function getMerchantStats(silent = false): Promise<MerchantStatsData> {
  return merchantRequest<MerchantStatsData>('/api/merchant/stats', { silent })
}