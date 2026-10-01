<template>
  <view class="weight">
    <!-- 未登录（§5.8 无权限态） -->
    <CNoPermission v-if="!userStore.isLogined" text="登录后记录体重" @action="goLogin" />

    <template v-else>
      <!-- 录入 -->
      <CCard title="记录体重" class="weight__card">
        <view class="weight__input-row">
          <CInput v-model="weightInput" type="digit" placeholder="如 68.5" />
          <text class="weight__unit">kg</text>
        </view>
        <CButton block :loading="saving" @click="onCreate">记录</CButton>
      </CCard>

      <!-- 趋势（用 view 拼简易柱状，勿引新依赖） -->
      <CCard title="趋势" class="weight__card">
        <CSkeleton v-if="loading" type="card" />
        <CError v-else-if="loadError" @retry="reload" />
        <template v-else>
          <view v-if="trend.length">
            <view class="weight__summary">
              <text class="weight__summary-item">起始 {{ summary.start }} kg</text>
              <text class="weight__summary-item">最新 {{ summary.latest }} kg</text>
              <text
                class="weight__summary-item"
                :class="summary.change <= 0 ? 'weight__summary-item--good' : 'weight__summary-item--bad'"
              >
                变化 {{ summary.change > 0 ? '+' : '' }}{{ summary.change }} kg
              </text>
            </view>
            <scroll-view scroll-x class="chart" :show-scrollbar="false">
              <view class="chart__bars">
                <view v-for="(p, i) in trend" :key="i" class="chart__col">
                  <text class="chart__val">{{ p.weight }}</text>
                  <view class="chart__bar" :style="{ height: barHeight(p.weight) }" />
                  <text class="chart__date">{{ p.date.slice(5) }}</text>
                </view>
              </view>
            </scroll-view>
          </view>
          <CEmpty v-else icon="empty-weight" text="还没有体重数据" button-text="" />
        </template>
      </CCard>

      <!-- 记录列表 -->
      <CCard title="记录列表" class="weight__card">
        <CSkeleton v-if="loading" type="line" :rows="3" />
        <template v-else>
          <CEmpty v-if="!records.length" icon="empty-weight" text="还没有体重记录" button-text="" />
          <view v-for="r in records" :key="r.id" class="weight__item">
            <view>
              <text class="weight__item-val">{{ r.weight }} kg</text>
              <text class="weight__item-date">{{ r.record_at }}</text>
            </view>
            <text class="weight__link--danger" @tap="onDelete(r)">删除</text>
          </view>
        </template>
      </CCard>
    </template>
  </view>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { useUserStore } from '@/stores/user'
import { redirectToLogin } from '@/utils/nav'
import { createWeight, listWeight, deleteWeight, getWeightTrend } from '@/api/weight'
import { useToast } from '@/composables/useToast'
import type { WeightRecordOut, WeightTrendItem } from '@/types/api'

const userStore = useUserStore()
const toast = useToast()

const loading = ref(false)
const loadError = ref(false)
const records = ref<WeightRecordOut[]>([])
const trend = ref<WeightTrendItem[]>([])

const weightInput = ref('')
const saving = ref(false)

/** 趋势摘要：起始 / 最新 / 变化 */
const summary = computed(() => {
  const ws = trend.value.map((t) => t.weight)
  if (!ws.length) return { start: 0, latest: 0, change: 0 }
  const start = ws[0]
  const latest = ws[ws.length - 1]
  return { start, latest, change: Math.round((latest - start) * 10) / 10 }
})

/** 柱高归一化：范围 [min, max]，映射到 20%~100%（差值过小时兜底 1kg） */
const barRange = computed(() => {
  const ws = trend.value.map((t) => t.weight)
  if (!ws.length) return { min: 0, max: 1 }
  const min = Math.min(...ws)
  const max = Math.max(...ws)
  return { min, max: max - min < 0.1 ? min + 1 : max }
})

function barHeight(w: number): string {
  const { min, max } = barRange.value
  const ratio = (w - min) / (max - min)
  return `${Math.round(20 + ratio * 80)}%`
}

onShow(() => {
  if (userStore.isLogined) reload()
})

async function reload() {
  loading.value = true
  loadError.value = false
  try {
    const [list, tr] = await Promise.all([listWeight({ page_size: 100 }), getWeightTrend()])
    records.value = list.items
    trend.value = tr.items
  } catch (e) {
    loadError.value = true
  } finally {
    loading.value = false
  }
}

function todayStr(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

async function onCreate() {
  const w = Number(weightInput.value)
  if (!w || w <= 0 || w > 500) {
    toast.error({ title: '请输入正确的体重（kg）' })
    return
  }
  saving.value = true
  try {
    await createWeight({ weight: w, record_at: todayStr(), source: 1 })
    toast.success({ title: '已记录' })
    weightInput.value = ''
    await reload()
  } catch (e) {
    // 错误信息已由 request 封装 toast
  } finally {
    saving.value = false
  }
}

/** 删除（二次确认，§13.2） */
function onDelete(r: WeightRecordOut) {
  uni.showModal({
    title: '确认删除',
    content: `删除 ${r.record_at} 的体重记录？`,
    success: async (res) => {
      if (!res.confirm) return
      try {
        await deleteWeight(r.id)
        toast.success({ title: '已删除' })
        await reload()
      } catch (e) {
        // 错误信息已由 request 封装 toast
      }
    },
  })
}

function goLogin() {
  redirectToLogin()
}
</script>

<style lang="scss" scoped>
.weight {
  padding: $space-md;

  &__card {
    margin-bottom: $space-md;
  }

  &__input-row {
    display: flex;
    align-items: center;
    margin-bottom: $space-md;

    :deep(.c-input) {
      flex: 1;
    }
  }

  &__unit {
    margin-left: $space-sm;
    font-size: $t-26;
    color: $text-2;
  }

  &__summary {
    @include flex-between;

    margin-bottom: $space-md;
  }

  &__summary-item {
    font-size: $t-22;
    color: $text-2;

    &--good {
      color: $success;
    }

    &--bad {
      color: $danger;
    }
  }

  &__item {
    @include flex-between;

    padding: $space-sm 0;

    &:not(:last-child) {
      @include hairline(bottom);
    }
  }

  &__item-val {
    display: block;
    font-size: $t-26;
    font-weight: 500;
    color: $text-1;
  }

  &__item-date {
    font-size: $t-22;
    color: $text-3;
  }

  &__link--danger {
    font-size: $t-24;
    color: $danger;
  }
}

.chart {
  width: 100%;
  height: 280rpx;
  white-space: nowrap;

  &__bars {
    display: flex;
    align-items: flex-end;
    height: 280rpx;
  }

  &__col {
    @include flex-center(column);

    flex-shrink: 0;
    width: 72rpx;
    height: 280rpx;
    justify-content: flex-end;
  }

  &__val {
    margin-bottom: $space-xs;
    font-size: $t-22;
    color: $text-3;
  }

  &__bar {
    width: 24rpx;
    min-height: 16rpx;
    background: $brand;
    border-radius: $radius-sm $radius-sm 0 0;
  }

  &__date {
    margin-top: $space-xs;
    font-size: $t-22;
    color: $text-3;
  }
}
</style>