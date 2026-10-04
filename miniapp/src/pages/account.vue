<template>
  <view class="page-shell">
    <CCard title="热量构成" class="detail__card">
      <CSkeleton v-if="accountStore.loading && !accountStore.today" type="card" />
      <template v-else-if="accountStore.today">
        <view class="detail__row">
          <text class="detail__label">基础代谢 BMR</text>
          <text class="detail__value">{{ fmt(today.bmr) }} kcal</text>
        </view>
        <view class="detail__row">
          <text class="detail__label">活动系数 PAL</text>
          <text class="detail__value">{{ today.pal.toFixed(1) }}</text>
        </view>
        <view class="detail__row">
          <text class="detail__label">校准消耗 NEAT</text>
          <text class="detail__value">{{ fmt(today.neat) }} kcal</text>
        </view>
        <view class="detail__row">
          <text class="detail__label">运动消耗 EAT</text>
          <text class="detail__value">{{ fmt(today.calories_burnt) }} kcal</text>
        </view>
        <view class="detail__row">
          <text class="detail__label">食物热效应 TEF</text>
          <text class="detail__value">{{ fmt(today.tef) }} kcal</text>
        </view>
        <view class="detail__row detail__row--strong">
          <text class="detail__label">每日总消耗 TEE</text>
          <text class="detail__value">{{ fmt(today.tee) }} kcal</text>
        </view>
      </template>
      <CError v-else @retry="reload" />
    </CCard>

    <CCard v-if="accountStore.today" title="今日收支" class="detail__card">
      <view class="detail__row">
        <text class="detail__label">已摄入</text>
        <text class="detail__value">{{ fmt(today.intake) }} kcal</text>
      </view>
      <view class="detail__row">
        <text class="detail__label">今日缺口</text>
        <text class="detail__value" :class="{ 'detail__value--danger': today.deficit < 0 }">
          {{ fmtSigned(today.deficit) }} kcal
        </text>
      </view>
      <view class="detail__row detail__row--highlight">
        <text class="detail__label">今天还能吃</text>
        <text class="detail__value" :class="{ 'detail__value--danger': accountStore.overBudget }">
          {{ fmtSigned(accountStore.left) }} kcal
        </text>
      </view>
      <view class="detail__row">
        <text class="detail__label">步数</text>
        <text class="detail__value">{{ fmt(today.steps) }} 步</text>
      </view>
      <view class="detail__row">
        <text class="detail__label">步数校准</text>
        <text class="detail__value">{{ today.calibration_used ? '已校准' : '未校准（按活动水平估算）' }}</text>
      </view>
    </CCard>

    <!-- 近 7 天趋势（account/trend + weight/trend）：三条曲线分开画，颜色对齐 tokens.scss
         摄入=$brand 绿 / TEE=$info 蓝 / 体重=$warn 琥珀（模板内取不到 SCSS 变量，写色值字面量） -->
    <CCard title="近 7 天趋势" class="detail__card">
      <CSkeleton v-if="trendLoading && !trendItems.length" type="line" :rows="4" />
      <CError v-else-if="trendError && !trendItems.length" @retry="reload" />
      <template v-else-if="trendItems.length">
        <view class="trend">
          <view class="trend__block">
            <view class="trend__head">
              <view class="trend__dot" :style="{ background: INTAKE_COLOR }" />
              <text class="trend__name">摄入（kcal）</text>
              <text v-if="lastIntake !== null" class="trend__latest">最新 {{ fmt(lastIntake) }}</text>
            </view>
            <CLineChart :points="intakePoints" :color="INTAKE_COLOR" :height="180" :min="0" />
          </view>

          <view class="trend__block">
            <view class="trend__head">
              <view class="trend__dot" :style="{ background: TEE_COLOR }" />
              <text class="trend__name">消耗 TEE（kcal）</text>
              <text v-if="lastTee !== null" class="trend__latest">最新 {{ fmt(lastTee) }}</text>
            </view>
            <CLineChart :points="teePoints" :color="TEE_COLOR" :height="180" :min="0" />
          </view>

          <view class="trend__block">
            <view class="trend__head">
              <view class="trend__dot" :style="{ background: WEIGHT_COLOR }" />
              <text class="trend__name">体重（kg）</text>
              <text v-if="lastWeight !== null" class="trend__latest">最新 {{ lastWeight }} kg</text>
            </view>
            <CLineChart
              v-if="hasWeight"
              :points="weightPoints"
              :color="WEIGHT_COLOR"
              :height="180"
            />
            <text v-else class="trend__empty">
              {{ weightLoading ? '体重曲线加载中…' : weightError ? '体重曲线暂不可用' : '近 7 天暂无体重记录' }}
            </text>
          </view>
        </view>
      </template>
      <CEmpty v-else icon="empty-weight" text="暂无趋势数据" button-text="去记录" @action="goRecord" />
    </CCard>
  </view>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { useAccountStore } from '@/stores/account'
import { useUserStore } from '@/stores/user'
import { redirectToLogin } from '@/utils/nav'
import { getTrend } from '@/api/account'
import { getWeightTrend } from '@/api/weight'
import type { DailyAccount, DailyTrendItem, WeightTrendItem } from '@/types/api'

const accountStore = useAccountStore()
const userStore = useUserStore()

const trendItems = ref<DailyTrendItem[]>([])
const trendLoading = ref(false)
const trendError = ref(false)

/** 空账户兜底（字段齐全，保证模板取值类型安全） */
const EMPTY_TODAY: DailyAccount = {
  date: '',
  bmr: 0,
  pal: 0,
  neat: 0,
  tef: 0,
  tee: 0,
  intake: 0,
  deficit: 0,
  steps: 0,
  calories_burnt: 0,
  calibration_used: false,
  today_left: 0,
  meals: [],
}

/** 今日账户（模板内简写） */
const today = computed(() => accountStore.today ?? EMPTY_TODAY)

function fmt(n: number): string {
  const v = Number.isFinite(n) ? n : 0
  return Math.round(Math.abs(v))
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, ',')
}
function fmtSigned(n: number): string {
  return (n < 0 ? '-' : '') + fmt(n)
}
/* ---------- 三条曲线：摄入 / TEE / 体重（CLineChart 纯 view 折线，不引图表库） ---------- */
/** 曲线配色对齐 tokens.scss（script 内取不到 SCSS 变量，写色值字面量，CRingProgress 同做法） */
const INTAKE_COLOR = '#22c55e' // $brand
const TEE_COLOR = '#3b82f6' // $info
const WEIGHT_COLOR = '#f59e0b' // $warn

interface LinePoint {
  label?: string
  value: number | null
}

/** 本地时区 YYYY-MM-DD（toISOString 是 UTC，凌晨会错切一天，与 sport.vue 同口径） */
function fmtDay(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/** 本地连续 7 天横轴（今日往前推），三条曲线共用 —— 保证三张图 x 轴逐点对齐 */
function weekSlots(): string[] {
  const out: string[] = []
  const today = new Date()
  for (let back = 6; back >= 0; back -= 1) {
    const d = new Date(today)
    d.setDate(d.getDate() - back)
    out.push(fmtDay(d))
  }
  return out
}

/**
 * 后端不补零（account/trend、weight/trend 都只返回有记录的日子）：
 * 统一按日期映射到共享 7 天横轴，缺记录的日子断线（value=null），
 * 点落在各自日期的固定位置 —— 不再「后端给几条画几条」导致单点居中、与横轴错位。
 */
function toLinePoints(rows: { date: string; value: number }[]): LinePoint[] {
  const byDate = new Map<string, number>()
  for (const row of rows) {
    const date = typeof row?.date === 'string' ? row.date.slice(0, 10) : ''
    const v = typeof row.value === 'number' && Number.isFinite(row.value) ? row.value : null
    if (date && v !== null) byDate.set(date, v)
  }
  return weekSlots().map((key) => ({ label: key.slice(5), value: byDate.get(key) ?? null }))
}

const intakePoints = computed<LinePoint[]>(() =>
  toLinePoints(trendItems.value.map((it) => ({ date: it.date, value: it.intake }))),
)
const teePoints = computed<LinePoint[]>(() =>
  toLinePoints(trendItems.value.map((it) => ({ date: it.date, value: it.tee }))),
)

/** 末位非空值（卡头「最新 N」展示；全空返回 null） */
function lastValue(points: LinePoint[]): number | null {
  for (let i = points.length - 1; i >= 0; i -= 1) {
    const v = points[i]?.value
    if (typeof v === 'number') return v
  }
  return null
}

const lastIntake = computed(() => lastValue(intakePoints.value))
const lastTee = computed(() => lastValue(teePoints.value))

/* ---------- 体重曲线（/api/weight/trend，取与摄入/TEE 相同的 7 天窗；失败只降级不影响主趋势） ---------- */
const weightItems = ref<WeightTrendItem[]>([])
const weightLoading = ref(false)
const weightError = ref(false)

async function fetchWeight() {
  weightLoading.value = true
  weightError.value = false
  try {
    const end = new Date()
    const start = new Date()
    start.setDate(start.getDate() - 6)
    const data = await getWeightTrend({ start_date: fmtDay(start), end_date: fmtDay(end) })
    weightItems.value = Array.isArray(data?.items) ? data.items : []
  } catch (e) {
    weightError.value = true
  } finally {
    weightLoading.value = false
  }
}

/** 体重点：后端只返回有记录的日子 → 统一铺到共享 7 天横轴，缺记录断线不造数 */
const weightPoints = computed<LinePoint[]>(() => {
  const rows: { date: string; value: number }[] = []
  for (const it of weightItems.value) {
    if (typeof it?.weight === 'number' && Number.isFinite(it.weight) && it.weight > 0) {
      rows.push({ date: it.date, value: it.weight })
    }
  }
  return toLinePoints(rows)
})

const hasWeight = computed(() => weightPoints.value.some((p) => p.value !== null))
const lastWeight = computed(() => lastValue(weightPoints.value))

onShow(() => {
  if (!userStore.isLogined) {
    redirectToLogin()
    return
  }
  accountStore.refresh()
  fetchTrend()
  fetchWeight()
})

function reload() {
  accountStore.refresh()
  fetchTrend()
  fetchWeight()
}

async function fetchTrend() {
  trendLoading.value = true
  trendError.value = false
  try {
    const data = await getTrend(7)
    trendItems.value = data.items ?? []
  } catch (e) {
    trendError.value = true
  } finally {
    trendLoading.value = false
  }
}

function goRecord() {
  uni.navigateTo({ url: '/pages/record/camera' })
}
</script>

<style lang="scss" scoped>
.page-shell {
  padding: $space-md;
}

.detail {
  &__card {
    margin-bottom: $space-md;
  }

  &__row {
    @include flex-between;

    padding: $space-xs 0;

    &--strong .detail__value {
      font-weight: 700;
    }

    &--highlight {
      padding: $space-sm 0;

      .detail__value {
        font-size: $t-num-md;
        font-weight: 700;
        color: $brand;

        &--danger {
          color: $danger;
        }
      }
    }
  }

  &__label {
    font-size: $t-26;
    color: $text-2;
  }

  &__value {
    font-size: $t-26;
    font-weight: 500;
    color: $text-1;

    &--danger {
      color: $danger;
    }
  }
}

// 近 7 天趋势：三条曲线分开画（摄入 / 消耗 TEE / 体重），每条配同色圆点标题行
.trend {
  &__block + &__block {
    margin-top: $space-md;
  }

  &__head {
    display: flex;
    align-items: center;
    margin-bottom: $space-xs;
  }

  &__dot {
    width: 16rpx;
    height: 16rpx;
    margin-right: $space-xs;
    border-radius: 4rpx;
  }

  &__name {
    flex: 1;
    font-size: $t-22;
    color: $text-2;
  }

  &__latest {
    font-size: $t-22;
    color: $text-3;
  }

  // 无体重数据时的占位行：高度与 CLineChart 一致，避免卡片跳动
  &__empty {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 180rpx;
    font-size: $t-22;
    color: $text-3;
  }
}
</style>