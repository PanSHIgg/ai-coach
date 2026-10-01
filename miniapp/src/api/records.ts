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

/** 步数同步结果 + 是否拿到真实微信运动数据（供页面区分提示文案） */
export interface WeRunStepsSyncResult {
  data: StepsSyncData
  /** true=取到微信运动加密数据（走后端解密）；false=未取到，已按活动水平估算 */
  gotWeRunData: boolean
}

/** 尝试获取微信运动加密数据；平台不支持/未授权/失败 → null（绝不伪造步数） */
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
 * 同步当日步数（§2.3.1 步数自动同步 / §13.3 取不到不报错）。
 *
 * - 优先上报真实微信运动加密数据（encrypted_data/iv），由后端解密取步数；
 * - 未取到（平台不支持/未授权/失败）→ steps 传 0，由后端按 PAL 估算 NEAT；
 * - 后端无解密能力/解密失败 → steps 已为 0，同样按 PAL 估算；
 * - **严禁伪造任何步数常量**（原 8000 mock 兜底已移除）。
 */
export async function syncStepsFromWeRun(date: string): Promise<WeRunStepsSyncResult> {
  const weRun = await getWeRunData()
  const payload: StepsSyncIn = { date, steps: 0 }
  if (weRun) {
    payload.encrypted_data = weRun.encryptedData
    payload.iv = weRun.iv
  }
  const data = await syncSteps(payload)
  return { data, gotWeRunData: weRun !== null }
}
