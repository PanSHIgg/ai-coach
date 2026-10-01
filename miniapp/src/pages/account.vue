<template>
  <view class="page-shell">
    <!-- 今日热量构成 -->
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

    <!-- 今日收支 -->
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

    <!-- 近 7 天趋势（account/trend，view 拼柱状图，不引新依赖） -->
    <CCard title="近 7 天趋势" class="detail__card">
      <CSkeleton v-if="trendLoading && !trendItems.length" type="line" :rows="4" />
      <CError v-else-if="trendError && !trendItems.length" @retry="fetchTrend" />
      <template v-else-if="trendItems.length">
        <view class="legend">
          <view class="legend__item"><view class="legend__dot legend__dot--intake" />摄入</view>
          <view class="legend__item"><view class="legend__dot legend__dot--tee" />消耗 TEE</view>
        </view>
        <view class="chart">
          <view v-for="it in trendItems" :key="it.date" class="chart__col">
            <view class="chart__bars">
              <view
                class="chart__bar chart__bar--intake"
                :class="{ 'chart__bar--over': it.intake > it.tee }"
                :style="{ height: barHeight(it.intake) }"
              />
              <view class="chart__bar chart__bar--tee" :style="{ height: barHeight(it.tee) }" />
            </view>
            <text class="chart__label">{{ shortDate(it.date) }}</text>
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
import type { DailyAccount, DailyTrendItem } from '@/types/api'

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
function shortDate(d: string): string {
  return d.length >= 10 ? d.slice(5) : d // YYYY-MM-DD → MM-DD
}

/** 柱状图最大刻度（摄入 / TEE 取全局最大，避免除零） */
const maxVal = computed(() => {
  const vals = trendItems.value.flatMap((i) => [i.intake, i.tee])
  return Math.max(1, ...vals)
})
function barHeight(v: number): string {
  return `${Math.max(2, Math.round((v / maxVal.value) * 100))}%`
}

onShow(() => {
  if (!userStore.isLogined) {
    redirectToLogin()
    return
  }
  accountStore.refresh()
  fetchTrend()
})

function reload() {
  accountStore.refresh()
  fetchTrend()
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

.legend {
  display: flex;
  gap: $space-md;
  margin-bottom: $space-md;

  &__item {
    display: flex;
    align-items: center;
    font-size: $t-22;
    color: $text-2;
  }

  &__dot {
    width: 16rpx;
    height: 16rpx;
    margin-right: $space-xs;
    border-radius: 4rpx;

    &--intake {
      background: $brand;
    }

    &--tee {
      background: $border;
    }
  }
}

.chart {
  display: flex;
  align-items: flex-end;
  height: 280rpx;

  &__col {
    flex: 1;
    height: 100%;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: flex-end;
  }

  &__bars {
    flex: 1;
    width: 100%;
    display: flex;
    align-items: flex-end;
    justify-content: center;
    gap: 4rpx;
  }

  &__bar {
    width: 18rpx;
    border-radius: 6rpx 6rpx 0 0;
    transition: height $duration-base $ease-out;

    &--intake {
      background: $brand;

      &.chart__bar--over {
        background: $danger;
      }
    }

    &--tee {
      background: $border;
    }
  }

  &__label {
    margin-top: $space-xs;
    font-size: $t-22;
    color: $text-3;
  }
}
</style>