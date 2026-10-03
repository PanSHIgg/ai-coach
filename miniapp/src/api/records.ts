/**
 * records API · 记录：食物搜索 / 饮食 CRUD / 运动 / 步数
 */
import type {
  FoodSearchIn,
  FoodSearchData,
  FoodCustomIn,
  FoodCustomData,
  MealCreateIn,
  MealCreatedData,
  MealUpdateIn,
  MealPageData,
  SportIn,
  SportCreatedData,
  SportPageData,
  StepsSyncIn,
  StepsSyncData,
  StepsTrendData,
  MealDeleteData,
} from '@/types/api'
import { request } from './request'

/** 食物搜索（关键词 + 数量） */
export function searchFood(data: FoodSearchIn) {
  return request<FoodSearchData>('/api/food/search', { method: 'POST', data })
}

/** 新建用户自定义食物（仅本人可见，待审核） */
export function createCustomFood(data: FoodCustomIn) {
  return request<FoodCustomData>('/api/food/custom', { method: 'POST', data })
}

/** 新建饮食记录 */
export function createMeal(data: MealCreateIn) {
  return request<MealCreatedData>('/api/meal', { method: 'POST', data })
}

/** 修改饮食记录 */
export function updateMeal(id: number, data: MealUpdateIn) {
  return request<MealCreatedData>(`/api/meal/${id}`, { method: 'PUT', data })
}

/** 删除饮食记录 */
export function deleteMeal(id: number) {
  return request<MealDeleteData>(`/api/meal/${id}`, { method: 'DELETE' })
}

/** 饮食记录分页列表 */
export function listMeals(params?: { page?: number; page_size?: number; date?: string }) {
  return request<MealPageData>('/api/meal/list', { data: params })
}

/** 新建运动记录 */
export function createSport(data: SportIn) {
  return request<SportCreatedData>('/api/sport', { method: 'POST', data })
}

/** 运动记录分页列表 */
export function listSports(params?: { page?: number; page_size?: number; date?: string }) {
  return request<SportPageData>('/api/sport/list', { data: params })
}

/** 步数同步（微信运动 → NEAT 校准） */
export function syncSteps(data: StepsSyncIn) {
  return request<StepsSyncData>('/api/steps/sync', { method: 'POST', data })
}

/**
 * 步数曲线的最大回看天数（契约 /api/steps/trend?days 的 maximum=31，
 * 与微信运动 stepInfoList 一次返回的条数一致）。页面按此长度铺横轴，勿自行写死。
 */
export const STEPS_TREND_MAX_DAYS = 31

/**
 * 近 N 天步数曲线数据（GET /api/steps/trend，契约 operationId=getStepsTrend）。
 *
 * - days 夹到 1..31（含 NaN 兜底）后作为 query 发出，避免打出一个必被 2001/422 拒掉的请求；
 * - ⚠️ **后端不补零**：items 只含「有记录」的日期（按日期升序）。
 *   "没同步过的日期" 与 "当天走了 0 步" 是两件事，页面须分开展示（见 pages/sport.vue）。
 */
export function getStepsTrend(days: number = STEPS_TREND_MAX_DAYS) {
  const requested = Number.isFinite(days) ? Math.round(days) : STEPS_TREND_MAX_DAYS
  const safe = Math.min(STEPS_TREND_MAX_DAYS, Math.max(1, requested))
  return request<StepsTrendData>('/api/steps/trend', { data: { days: safe } })
}

/**
 * 微信运动取数三态（取代原 gotWeRunData 单一 boolean，页面据此区分文案与引导入口）。
 * 注意：granted 只代表「客户端拿到了加密数据」，**是否真有真实步数以后端 steps_source 为准**。
 */
export type WeRunSyncStatus =
  /** 已授权 scope.werun 且取到 encryptedData/iv（待后端解密确认） */
  | 'granted'
  /** 未授权 scope.werun（曾拒绝 / 本次拒绝 / getSetting 不可判定）→ 可引导 openSetting */
  | 'unauthorized'
  /** 已授权但取不到：开发者工具模拟器无计步数据 / getWeRunData 失败 / 非微信平台无该能力 */
  | 'unavailable'

/** 后端步数真源（contracts StepsSyncData.steps_source）：1=微信运动解密成功 2=客户端传入 steps 3=未取到，按 PAL 估算 */
export type StepsSource = 1 | 2 | 3

/** 步数同步结果 + 客户端取数态 + 后端真源（页面须据此如实提示，不得凭"getWeRunData 成功"自行推断） */
export interface WeRunStepsSyncResult {
  /** 后端原始响应（步数真源在这里） */
  data: StepsSyncData
  /** 客户端授权 / 取数三态 */
  status: WeRunSyncStatus
  /** 后端回传的真源；undefined=后端尚未回传（联调期），一律按最保守口径处理 */
  source: StepsSource | undefined
  /** 仅当后端确认 source===1 才为 true —— 只有此时页面才能说"已同步微信运动 N 步" */
  isRealSteps: boolean
  /** 后端确认的实际入库步数（未回传/非法 → 0，前端绝不造数） */
  steps: number
}

/** 同步结果展示口径（文案真源＝后端 steps_source，一处生成、多页复用，避免各页文案漂移） */
export interface StepsSyncMessage {
  /** success=后端确认真实步数已入库；info=估算/降级 */
  tone: 'success' | 'info'
  /** Toast 短文案 */
  title: string
  /** 页面内联「步数来源」说明（Toast 1.5s 即逝，来源需常驻，§2.4） */
  sourceLabel: string
  /** 未授权 → 需要「去开启微信运动」引导入口（uni.openSetting） */
  needGuide: boolean
}

/** 千分位格式化（小程序 toLocaleString 分组不可靠，与各页面 fmt 同口径） */
function fmtThousands(n: number): string {
  return Math.round(Math.abs(n))
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, ',')
}

/** 读后端 steps_source；后端并行开发中可能缺字段 → undefined（最保守口径） */
function readStepsSource(data: StepsSyncData): StepsSource | undefined {
  const raw = (data as unknown as Record<string, unknown> | null | undefined)?.steps_source
  return raw === 1 || raw === 2 || raw === 3 ? raw : undefined
}

/** 读后端实际入库步数；缺失/非法一律 0（不回退任何常量，避免谎报） */
function readSyncedSteps(data: StepsSyncData): number {
  const raw = (data as unknown as Record<string, unknown> | null | undefined)?.steps
  return typeof raw === 'number' && Number.isFinite(raw) && raw > 0 ? Math.round(raw) : 0
}

/**
 * 读「本次顺带回填的历史天数（不含当天）」。
 * 缺失 / 非法 / ≤0 一律 0 —— 后端没明确回传就不提回填，绝不把"曲线里有柱子"当成回填证据。
 */
function readBackfilledDays(data: StepsSyncData): number {
  const raw = (data as unknown as Record<string, unknown> | null | undefined)?.backfilled_days
  return typeof raw === 'number' && Number.isFinite(raw) && raw > 0 ? Math.floor(raw) : 0
}

/**
 * 生成同步结果展示口径。
 * 严禁在后端未确认（source 缺失或为 2/3）时宣称取到了真实步数。
 * 三种降级情形分开说：未授权 / 已授权但后端未确认真实步数 / 已授权但客户端就没取到。
 * 「已回填最近 M 天历史」只在后端确认真实步数（steps_source=1）且回传 backfilled_days>0 时出现
 * （契约口径：仅 source=1 可能 >0；估算分支即使拿到该字段也不报，避免谎报历史）。
 */
export function describeStepsSync(res: WeRunStepsSyncResult): StepsSyncMessage {
  if (res.isRealSteps) {
    const delta = Math.round(Number(res.data?.delta_calories) || 0)
    const backfilled = readBackfilledDays(res.data)
    // 回填只在后端明确回传 backfilled_days>0 时才报；Toast 与常驻来源行都说一遍（曲线是唯一能看见回填的地方）
    const backfillTitle = backfilled > 0 ? `，已回填最近 ${backfilled} 天历史` : ''
    const backfillLabel = backfilled > 0 ? ` · 已回填最近 ${backfilled} 天历史` : ''
    return {
      tone: 'success',
      title: `已同步微信运动 ${fmtThousands(res.steps)} 步，校准 +${delta} kcal${backfillTitle}`,
      sourceLabel: `步数来源：微信运动真实数据（${fmtThousands(res.steps)} 步${backfillLabel}）`,
      needGuide: false,
    }
  }
  // 后端未确认真实步数（source=2/3/缺失）→ 一律如实说"按活动水平估算"
  if (res.status === 'unauthorized') {
    return {
      tone: 'info',
      title: '未授权微信运动，步数按活动水平估算',
      sourceLabel: '步数来源：活动水平估算（未授权微信运动）',
      needGuide: true,
    }
  }
  if (res.status === 'granted') {
    // 加密数据已上报，但后端解密失败 / 该日无微信运动记录 → 不能说"同步成功"
    return {
      tone: 'info',
      title: '微信运动未取到真实步数，按活动水平估算',
      sourceLabel: '步数来源：活动水平估算（微信运动未返回该日步数，绑定手环更精准）',
      needGuide: false,
    }
  }
  return {
    tone: 'info',
    title: '未取到微信步数，已按活动水平估算',
    sourceLabel: '步数来源：活动水平估算（未取到微信运动步数，绑定手环更精准）',
    needGuide: false,
  }
}

/**
 * 未授权引导（§2.4「引导跳转设置页开启，不阻断核心流程」）。
 * 微信官方口径：authorize 被拒后再次请求会**直接失败且不再弹框**，只能由用户 openSetting 手动开启。
 * 引导本身可被取消且取消不影响本次同步（估算值已入库）。
 */
export function guideToWeRunSetting() {
  // #ifdef MP-WEIXIN
  uni.showModal({
    title: '开启微信运动',
    content: '未授权微信运动，步数只能按活动水平估算。前往设置开启后可同步真实步数。',
    confirmText: '去设置',
    cancelText: '暂不',
    success: (res) => {
      if (res.confirm) uni.openSetting({})
    },
  })
  // #endif
}

/** scope.werun 授权态读取结果（仅微信端） */
type WeRunAuthState = 'authorized' | 'unauthorized' | 'unsupported'

/**
 * scope.werun 授权预检（微信官方口径：取微信运动数据前先 getSetting 查授权）。
 *
 * 运行时三态（AuthSetting 类型上写的是 boolean，实际未决定时该键不存在）：
 * - true  已授权 → 放行；
 * - false 曾拒绝 → **不再调 authorize**（会直接失败且不弹框），判未授权，由页面引导 openSetting；
 * - 缺键  未决定 → authorize 主动申请（首次会弹框），拒绝即未授权。
 *
 * 任何分支都 resolve、不 reject、不抛错：未授权只降级估算，不阻断本次同步（§2.4）。
 */
function preflightWeRunAuth(): Promise<WeRunAuthState> {
  return new Promise((resolve) => {
    // #ifdef MP-WEIXIN
    uni.getSetting({
      success: (res) => {
        const granted = (res.authSetting ?? {}) as unknown as Record<string, boolean | undefined>
        const werun = granted['scope.werun']
        if (werun === true) {
          resolve('authorized')
          return
        }
        if (werun === false) {
          resolve('unauthorized')
          return
        }
        // 未决定 → 申请授权
        uni.authorize({
          scope: 'scope.werun',
          success: () => resolve('authorized'),
          fail: () => resolve('unauthorized'),
        })
      },
      // getSetting 失败 → 授权态不可判定，按未授权处理（仍不阻断，页面给引导入口）
      fail: () => resolve('unauthorized'),
    })
    // #endif
    // #ifndef MP-WEIXIN
    // 非微信小程序平台（仅 H5 编译检查通道）无微信运动能力：标 unsupported，避免出现无意义的「去开启」引导
    resolve('unsupported')
    // #endif
  })
}

/** 取微信运动加密数据（先做 scope.werun 授权预检）；失败/未授权 → null（绝不伪造步数） */
function getWeRunData(): Promise<{ encryptedData: string; iv: string } | null> {
  return new Promise((resolve) => {
    // #ifdef MP-WEIXIN
    uni.getWeRunData({
      success: (res) => {
        if (res.encryptedData && res.iv) {
          resolve({ encryptedData: res.encryptedData, iv: res.iv })
        } else {
          resolve(null)
        }
      },
      fail: () => resolve(null),
    })
    // #endif
    // #ifndef MP-WEIXIN
    resolve(null)
    // #endif
  })
}

/**
 * 授权预检 + 取加密数据，产出三态（① granted 已授权并取到加密数据 ② unauthorized 未授权 ③ unavailable 已授权但取不到）。
 * 两个 #ifdef/#ifndef 分支编译期只保留一条，运行时不会同时执行（与 getWeRunData 同写法）。
 */
function fetchWeRunEncrypted(): Promise<{ status: WeRunSyncStatus; encrypted: { encryptedData: string; iv: string } | null }> {
  return new Promise((resolve) => {
    // #ifdef MP-WEIXIN
    preflightWeRunAuth().then((auth) => {
      if (auth !== 'authorized') {
        resolve({ status: auth === 'unauthorized' ? 'unauthorized' : 'unavailable', encrypted: null })
        return
      }
      getWeRunData().then((encrypted) => {
        resolve({ status: encrypted ? 'granted' : 'unavailable', encrypted })
      })
    })
    // #endif
    // #ifndef MP-WEIXIN
    resolve({ status: 'unavailable', encrypted: null })
    // #endif
  })
}

/**
 * 同步当日步数（§2.3.1 步数自动同步 / §2.4 取不到降级 / §13.3 取不到不报错）。
 *
 * - 先 getSetting/authorize 预检 scope.werun，再取微信运动加密数据（encrypted_data/iv）交后端解密；
 * - 未授权 / 取不到 → steps 传 0，由后端按 PAL 估算 NEAT，流程不阻断；
 * - **是否真取到真实步数由后端 steps_source 判定**（1 才是真），前端不再凭"getWeRunData 成功"自行推断；
 * - **严禁伪造任何步数常量**（原 8000 mock 兜底已移除）。
 */
export async function syncStepsFromWeRun(date: string): Promise<WeRunStepsSyncResult> {
  const { status, encrypted } = await fetchWeRunEncrypted()
  const payload: StepsSyncIn = { date, steps: 0 }
  if (encrypted) {
    payload.encrypted_data = encrypted.encryptedData
    payload.iv = encrypted.iv
  }
  const data = await syncSteps(payload)
  const source = readStepsSource(data)
  return { data, status, source, isRealSteps: source === 1, steps: readSyncedSteps(data) }
}
