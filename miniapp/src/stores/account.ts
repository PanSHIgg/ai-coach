/**
 * account store · 今日热量账户（首页热量环数据源）
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { DailyAccount } from '@/types/api'
import { getToday } from '@/api/account'

export const useAccountStore = defineStore('account', () => {
  const today = ref<DailyAccount | null>(null)
  const loading = ref(false)

  /** 热量环百分比：摄入 / TEE，0-100 钳制 */
  const percent = computed(() => {
    if (!today.value || !today.value.tee) return 0
    return Math.min(100, Math.round((today.value.intake / today.value.tee) * 100))
  })

  /** 剩余预算 kcal（负值 = 已超标） */
  const left = computed(() => {
    if (!today.value) return 0
    return Math.round(today.value.tee - today.value.intake)
  })

  /** 拉今日账户（onShow 调用，mock 50-150ms 延迟） */
  async function fetchToday() {
    loading.value = true
    try {
      today.value = await getToday()
    } finally {
      loading.value = false
    }
  }

  return { today, loading, percent, left, fetchToday }
})
