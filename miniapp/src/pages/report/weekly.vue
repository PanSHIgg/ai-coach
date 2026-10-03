<template>
  <view class="wk">
    <!-- 未登录（§5.8 无权限态） -->
    <CNoPermission v-if="!userStore.isLogined" text="登录后查看周报" @action="goLogin" />

    <template v-else>
      <CSkeleton v-if="loading" type="card" />
      <CError v-else-if="error" @retry="load" />
      <CEmpty
        v-else-if="!report || !report.days.length"
        icon="empty-food"
        text="本周还没有记录"
        button-text=""
      />
      <template v-else>
        <!-- 概览：缺口控制率环 + 三项均值 -->
        <CCard title="本周概览" class="wk__card">
          <text class="wk__period">{{ periodText }}</text>
          <view class="wk__overview">
            <CRingProgress :percent="deficitRatio" :size="180" :stroke-width="20" color="#22c55e">
              <view class="wk__ring">
                <text class="wk__ring-num">{{ deficitDays }}/{{ totalDays }}</text>
                <text class="wk__ring-label">有缺口天数</text>
              </view>
            </CRingProgress>
            <view class="wk__metrics">
              <view class="wk__metric">
                <text class="wk__metric-k">平均缺口</text>
                <text class="wk__metric-v">{{ deficitText }}</text>
              </view>
              <view class="wk__metric">
                <text class="wk__metric-k">平均步数</text>
                <text class="wk__metric-v">{{ Math.round(report.steps_avg) }} 步</text>
              </view>
              <view class="wk__metric">
                <text class="wk__metric-k">体重变化</text>
                <text
                  class="wk__metric-v"
                  :class="weightClass"
                >
                  {{ weightText }}
                </text>
              </view>
            </view>
          </view>
        </CCard>

        <CCard title="每日趋势" class="wk__card">
          <view class="wk__head">
            <text class="wk__col wk__col--date">日期</text>
            <text class="wk__col">缺口</text>
            <text class="wk__col">步数</text>
            <text class="wk__col">体重</text>
          </view>
          <view v-for="d in report.days" :key="d.date" class="wk__row">
            <text class="wk__col wk__col--date">{{ d.date.slice(5) }}</text>
            <text class="wk__col">{{ numText(d.deficit) }}</text>
            <text class="wk__col">{{ d.steps == null ? '—' : d.steps }}</text>
            <text class="wk__col">{{ d.weight == null ? '—' : d.weight }}</text>
          </view>
        </CCard>

        <CCard title="AI 点评" class="wk__card">
          <text class="wk__comment">{{ report.comment }}</text>
        </CCard>
      </template>
    </template>
  </view>
</template>

<script setup lang="ts">
/**
 * FE · 热量控制周报 — G3 / G12
 * 依据：docs/split/01 §2.3.1-7、docs/split/06 §1.3（每周周报：缺口、步数、体重趋势、AI 点评）
 * 契约：GET /api/report/weekly（period/intake_avg/deficit_avg/steps_avg/weight_change/comment/days）
 * 【假设】① 环形进度展示「有缺口天数占比」（deficit<0 视为当日达成缺口），无需后端额外下发目标；
 *         ② deficit_avg 为负值代表缺口，展示取绝对值并标注 kcal；体重变化为空时显示 —。
 */
import { computed, ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { useUserStore } from '@/stores/user'
import { redirectToLogin } from '@/utils/nav'
import { getWeeklyReport } from '@/api/report'
import type { WeeklyReportData } from '@/types/api'

const userStore = useUserStore()

const report = ref<WeeklyReportData | null>(null)
const loading = ref(false)
const error = ref(false)

/** 期号（可选）：?week=YYYY-Www */
let week = ''

const totalDays = computed(() => report.value?.days.length ?? 0)

/** 有缺口（deficit<0）的天数 */
const deficitDays = computed(
  () => report.value?.days.filter((d) => d.deficit != null && d.deficit < 0).length ?? 0,
)

const deficitRatio = computed(() =>
  totalDays.value ? Math.round((deficitDays.value / totalDays.value) * 100) : 0,
)

const periodText = computed(() => {
  const p = report.value?.period
  return p ? `${p.start} ~ ${p.end}` : ''
})

const deficitText = computed(() => {
  const v = report.value?.deficit_avg ?? 0
  return `${Math.round(Math.abs(v))} kcal`
})

const weightText = computed(() => {
  const v = report.value?.weight_change
  if (v == null) return '—'
  return `${v > 0 ? '+' : ''}${v} kg`
})

const weightClass = computed(() => {
  const v = report.value?.weight_change
  if (v == null || v === 0) return ''
  return v > 0 ? 'wk__metric-v--bad' : 'wk__metric-v--good'
})

function numText(n?: number | null): string {
  return n == null ? '—' : `${Math.round(n)}`
}

onLoad((options) => {
  week = (options?.week as string) || ''
  if (userStore.isLogined) load()
})

async function load() {
  loading.value = true
  error.value = false
  try {
    report.value = await getWeeklyReport(week || undefined)
  } catch (e) {
    report.value = null
    error.value = true
    void e
  } finally {
    loading.value = false
  }
}

function goLogin() {
  redirectToLogin()
}
</script>

<style lang="scss" scoped>
.wk {
  padding: $space-md;

  &__card {
    margin-bottom: $space-md;
  }

  &__period {
    display: block;
    margin-bottom: $space-md;
    font-size: $t-22;
    color: $text-3;
  }

  &__overview {
    display: flex;
    align-items: center;
  }

  &__ring {
    @include flex-center(column);
  }

  &__ring-num {
    font-size: $t-32;
    font-weight: 700;
    color: $text-1;
  }

  &__ring-label {
    margin-top: 4rpx;
    font-size: $t-22;
    color: $text-3;
  }

  &__metrics {
    flex: 1;
    margin-left: $space-lg;
  }

  &__metric {
    display: flex;
    align-items: baseline;
    justify-content: space-between;

    &:not(:last-child) {
      margin-bottom: $space-sm;
    }
  }

  &__metric-k {
    font-size: $t-22;
    color: $text-3;
  }

  &__metric-v {
    font-size: $t-26;
    font-weight: 500;
    color: $text-1;

    &--good {
      color: $success;
    }

    &--bad {
      color: $danger;
    }
  }

  &__head {
    @include flex-between;

    padding-bottom: $space-xs;
    @include hairline(bottom);
  }

  &__row {
    @include flex-between;

    padding: $space-xs 0;

    &:not(:last-child) {
      @include hairline(bottom);
    }
  }

  &__col {
    flex: 1;
    font-size: $t-22;
    color: $text-2;
    text-align: center;

    &--date {
      flex: 1.2;
      color: $text-1;
      text-align: left;
    }
  }

  &__comment {
    display: block;
    font-size: $t-24;
    line-height: 1.6;
    color: $text-2;
  }
}
</style>