/**
 * account store · 今日热量账户（首页热量环数据源）
 *
 * 环形图「今天还能吃」口径（01 §2.5 / plan §7 退出标准）：
 *   today_left = BMR×PAL − 已摄入 + 运动消耗 − TEF
 * 以契约 today_left 为唯一真值；后端未联调 / Mock 缺字段时按同口径兜底，
 * 后端一旦返回 today_left 即直接采用，切换真接口零改动。
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { DailyAccount, TodayStatusIn } from '@/types/api'
import { getToday, setTodayStatus as setTodayStatusApi } from '@/api/account'

export const useAccountStore = defineStore('account', () => {
  const today = ref<DailyAccount | null>(null)
  const loading = ref(false)
  const error = ref(false)

  /** 每日预算 kcal = BMR × PAL（§5.1「预算 2,100」= BMR×PAL） */
  const budget = computed(() => {
    const t = today.value
    if (!t) return 0
    return Math.round(t.bmr * t.pal)
  })

  /** 今天还能吃 kcal（负值 = 已超标）：优先契约 today_left，缺失按同口径兜底 */
  const left = computed(() => {
    const t = today.value
    if (!t) return 0
    if (typeof t.today_left === 'number') return Math.round(t.today_left)
    return Math.round(t.bmr * t.pal - t.intake + t.calories_burnt - t.tef)
  })

  /** 是否已超标 */
  const overBudget = computed(() => left.value < 0)

  /** 热量环进度：已摄入 / 预算（钳制 0-100） */
  const percent = computed(() => {
    if (!budget.value) return 0
    const intake = today.value?.intake ?? 0
    return Math.min(100, Math.max(0, Math.round((intake / budget.value) * 100)))
  })

  /** 拉取今日账户（错误会抛出，调用方可 catch 展示错误态） */
  async function fetchToday() {
    loading.value = true
    error.value = false
    try {
      today.value = await getToday()
    } catch (e) {
      error.value = true
      throw e
    } finally {
      loading.value = false
    }
  }

  /**
   * 刷新今日账户（onShow、拍照或记录返回后调用）。
   * 与 fetchToday 区别：内部吞掉异常，仅置 error 标记供页面展示 CError，不打断调用方。
   */
  async function refresh() {
    try {
      await fetchToday()
    } catch (e) {
      // 错误信息已由 request 封装 toast；此处保留 error 标记即可
    }
  }

  /**
   * 写入当日状态（F-01，§2.3.1 五选一）并刷新今日账户。
   * 失败会抛出（由调用方决定是否打扰用户）；成功直接采用接口返回的最新账户。
   */
  async function setTodayStatus(level: TodayStatusIn['activity_level']) {
    today.value = await setTodayStatusApi(level)
  }

  return {
    today,
    loading,
    error,
    budget,
    left,
    overBudget,
    percent,
    refresh,
    fetchToday,
    setTodayStatus,
  }
})