<template>
  <div>
    <el-alert
      v-if="isFallback"
      title="后端未连接，展示演示数据"
      type="warning"
      show-icon
      :closable="false"
      class="fallback-alert"
    />

    <el-alert v-if="error" type="error" show-icon :closable="false" class="fallback-alert">
      <template #title>
        <span>{{ error }}</span>
        <el-button link type="primary" size="small" class="retry-btn" @click="load">重试</el-button>
      </template>
    </el-alert>

    <el-row v-loading="loading" :gutter="16">
      <el-col v-for="card in cards" :key="card.label" :xs="24" :sm="12" :md="8" :lg="4">
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
import { isNetworkError } from '@/api/client'
import type { DashboardData } from '@/types/api'

const data = ref<DashboardData | null>(null)
const isFallback = ref(false)
const loading = ref(false)
const error = ref<string | null>(null)

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

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    data.value = await getDashboard()
    isFallback.value = false
  } catch (err) {
    if (isNetworkError(err)) {
      // 后端未启动：走内置演示数据，保证看板不白屏
      data.value = FALLBACK
      isFallback.value = true
    } else {
      // 403/5xx 等真实错误：明确提示并给重试入口，不再伪装成演示数据
      data.value = null
      isFallback.value = false
      error.value = err instanceof Error ? err.message : '看板加载失败'
    }
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.retry-btn {
  margin-left: 8px;
}

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
