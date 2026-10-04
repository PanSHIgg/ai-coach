/**
 * useRecordCombo · 把「组合 / 套餐」写入今日饮食记录的公共逻辑
 *
 * 服务两处：吃什么页 AI 推荐卡（source=4）与菜单识别推荐页。
 * 【假设】createMeal 需 food_id + amount_g，而组合只给 name + calories：
 *   ① 按 COMBO_SPLIT 拆成单品；② 逐条 searchFood 命中食物库；③ 热量按条数均分反推分量；
 *   ④ 全部未命中返回 0（调用方提示手动录入）。
 */
import { createMeal, searchFood } from '@/api/records'
import type { FoodItem } from '@/types/api'

/** 组合名分隔符：中英文加号 / 顿号 / 逗号 / 斜杠（如「清蒸鱼+炒青菜+半碗饭」） */
export const COMBO_SPLIT = /[+＋、,，/／]/

/** amount_g 上界（对齐后端 MealCreateIn 校验 0 < amount_g ≤ 10000） */
const AMOUNT_MAX = 10000

export function useRecordCombo() {
  /** 按关键词取第一个食物（无命中返回 null，不抛错打断流程） */
  async function findFood(keyword: string): Promise<FoodItem | null> {
    try {
      const data = await searchFood({ keyword, limit: 1 })
      return data?.items?.[0] ?? null
    } catch {
      return null
    }
  }

  /** 由目标热量 + 每 100g 热量反推分量（后端按 food_id + amount_g 重算 kcal） */
  function gramsFor(calories: number, calories100g: number): number {
    const per100 = calories100g > 0 ? calories100g : 100
    const grams = Math.round((calories / per100) * 100)
    return Math.min(AMOUNT_MAX, Math.max(1, grams))
  }

  /** 写入一个组合，返回成功条数；source：1拍照 3手动 4AI推荐 */
  async function recordCombo(
    name: string,
    calories: number,
    mealType: 1 | 2 | 3 | 4,
    source: 1 | 3 | 4 = 4,
  ): Promise<number> {
    const parts = name.split(COMBO_SPLIT).map((s) => s.trim()).filter(Boolean)
    const list = parts.length ? parts : [name.trim()]
    const perKcal = Math.round(calories / list.length)
    let count = 0
    for (const part of list) {
      const food = await findFood(part)
      if (!food) continue
      await createMeal({
        meal_type: mealType,
        food_id: food.id,
        amount_g: gramsFor(perKcal, food.calories_100g),
        source,
      })
      count += 1
    }
    return count
  }

  return { recordCombo }
}
