/**
 * records API · 记录：食物搜索 / 饮食 CRUD / 运动 / 步数
 */
import type {
  FoodSearchIn,
  FoodSearchData,
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
