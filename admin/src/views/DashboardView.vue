<template>
  <div>
    <el-alert
      v-if="isFallback"
      title="后端未连接，演示数据"
      type="warning"
      show-icon
      :closable="false"
      class="fallback-alert"
    />

    <el-row :gutter="16">
      <el-col v-for="card in cards" :key="card.label" :xs="12" :sm="8" :md="8" :lg="4">
        <el-card class="page-card stat-card">
          <div class="stat-label">{{ card.label }}</div>
          <div class="stat-value">{{ card.value }}</div>
        </el-card>
      </el-col>
    </el-row>

    <el-card class="page-card">
      <template #header>
        <span>看板日期：{{ data?.date ?? '-' }}</span>
      </template>
      <el-empty v-if="!data" description="暂无数据" />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { getDashboard } from '@/api/admin'
import type { DashboardData } from '@/types/api'

const data = ref<DashboardData | null>(null)
const isFallback = ref(false)

/** 后端未就绪时的内置演示数据 */
const FALLBACK: DashboardData = {
  date: new Date().toISOString().slice(0, 10),
  user_count: 328,
  active_users_today: 96,
  meal_records_today: 214,
  orders_today: 57,
  gmv_today: 4826.5,
  ai_calls_today: 731,
}

const cards = computed(() => {
  const d = data.value
  if (!d) return []
  return [
    { label: '累计用户', value: String(d.user_count) },
    { label: '今日活跃用户', value: String(d.active_users_today) },
    { label: '今日饮食记录', value: String(d.meal_records_today) },
    { label: '今日订单', value: String(d.orders_today) },
    { label: '今日 GMV', value: `¥${d.gmv_today.toFixed(2)}` },
    { label: '今日 AI 调用', value: String(d.ai_calls_today) },
  ]
})

onMounted(async () => {
  try {
    data.value = await getDashboard()
    isFallback.value = false
  } catch {
    data.value = FALLBACK
    isFallback.value = true
  }
})
</script>

<style scoped>
.stat-card {
  text-align: center;
}

.stat-label {
  font-size: 13px;
  color: #6b7280;
  margin-bottom: 8px;
}

.stat-value {
  font-size: 24px;
  font-weight: 700;
  color: #16a34a;
}
</style>
