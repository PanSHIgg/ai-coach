<template>
  <view class="home">
    <!-- 顶部问候 / 日期 + 档案入口（§5.1 顶部栏） -->
    <view class="home__header">
      <view class="home__hello">
        <text class="home__greet">{{ greeting }}，{{ userStore.nickname }}</text>
        <text class="home__date">{{ todayText }}</text>
      </view>
      <view class="home__entry" @tap="goEditProfile">
        <text class="home__entry-text">{{ userStore.needProfile ? '立即建档' : '我的档案' }}</text>
        <text class="home__entry-arrow">›</text>
      </view>
    </view>

    <!-- 未建档引导（§5.1：未建档时首页展示建档引导） -->
    <CCard v-if="userStore.needProfile" class="home__guide">
      <view class="guide">
        <text class="guide__icon">📋</text>
        <view class="guide__main">
          <text class="guide__title">先建档，才能算出今天还能吃多少</text>
          <text class="guide__desc">填写性别 / 身高 / 体重 / 目标，1 分钟搞定</text>
        </view>
        <CButton size="sm" @click="goEditProfile">去建档</CButton>
      </view>
    </CCard>

    <!-- 热量账户环形图（§5.1：中心「今天还能吃」= today_left） -->
    <CCard
      title="今日热量"
      class="home__card"
      :class="{ 'home__card--dim': userStore.needProfile }"
    >
      <template #extra>
        <text class="link" @tap="goAccountDetail">详情 ›</text>
      </template>

      <CSkeleton v-if="accountStore.loading && !accountStore.today" type="card" />
      <CError v-else-if="accountStore.error && !accountStore.today" @retry="accountStore.refresh" />
      <CEmpty
        v-else-if="userStore.needProfile || !accountStore.today"
        icon="📋"
        text="建档后展示今日热量账户"
        button-text="去建档"
        @action="goEditProfile"
      />
      <template v-else>
        <view class="ring-wrap" @tap="goAccountDetail">
          <CRingProgress
            :percent="accountStore.percent"
            :color="ringColor"
            :size="280"
            :stroke-width="28"
          >
            <view class="ring-center">
              <text class="ring-center__num">{{ leftText }}</text>
              <text class="ring-center__label">{{ leftLabel }}</text>
            </view>
          </CRingProgress>
        </view>

        <view class="metrics">
          <view class="metrics__row">
            <text class="metrics__k">已摄入</text>
            <text class="metrics__v">{{ fmt(intake) }} kcal</text>
            <text class="metrics__k">预算</text>
            <text class="metrics__v">{{ fmt(accountStore.budget) }} kcal</text>
          </view>
          <view class="metrics__row">
            <text class="metrics__k">运动消耗</text>
            <text class="metrics__v metrics__v--plus">+{{ fmt(burnt) }} kcal</text>
            <text class="metrics__k">今日缺口</text>
            <text class="metrics__v" :class="{ 'metrics__v--danger': deficit < 0 }">
              {{ fmtSigned(deficit) }} kcal
            </text>
          </view>
        </view>

        <text v-if="accountStore.today?.calibration_used" class="calib">
          已根据微信步数动态校准 NEAT
        </text>
        <text v-else class="calib">暂按活动水平（{{ activityText }}）估算 NEAT</text>
      </template>
    </CCard>

    <!-- 摄入明细（§5.1：按餐次汇总） -->
    <CCard
      title="摄入明细"
      class="home__card"
      :class="{ 'home__card--dim': userStore.needProfile }"
    >
      <template #extra>
        <text class="link" @tap="goFoodList">全部 ›</text>
      </template>
      <view v-if="meals.length" class="meal-list">
        <view v-for="m in meals" :key="m.meal_type" class="meal-list__row" @tap="goFoodList">
          <text class="meal-list__name">{{ mealLabel(m) }}</text>
          <text class="meal-list__kcal">{{ fmt(m.calories) }} kcal</text>
        </view>
      </view>
      <CEmpty v-else icon="🍽️" :text="emptyMealText" @action="goCamera" />
    </CCard>

    <!-- 运动明细（§5.1：步数 + 运动消耗） -->
    <CCard
      title="运动明细"
      class="home__card"
      :class="{ 'home__card--dim': userStore.needProfile }"
    >
      <view class="sport">
        <view class="sport__item">
          <text class="sport__k">步数</text>
          <text class="sport__v">{{ fmt(steps) }} 步</text>
        </view>
        <view class="sport__item">
          <text class="sport__k">运动消耗</text>
          <text class="sport__v">{{ fmt(burnt) }} kcal</text>
        </view>
      </view>
      <view class="sport__actions">
        <CButton type="ghost" size="sm" @click="goSportAdd">+ 添加运动</CButton>
      </view>
    </CCard>

    <!-- 核心指标（§5.1：体重/BMI/BMR 等，缺失灰显占位） -->
    <CCard
      title="核心指标"
      class="home__card"
      :class="{ 'home__card--dim': userStore.needProfile }"
    >
      <view v-for="m in coreMetrics" :key="m.label" class="core">
        <text class="core__icon">{{ m.icon }}</text>
        <text class="core__label">{{ m.label }}</text>
        <text class="core__value" :class="{ 'core__value--empty': !m.value }">
          {{ m.value || '--' }}
        </text>
        <view class="core__bar">
          <view class="core__bar-fill" :style="{ width: m.bar + '%', background: m.color }" />
        </view>
      </view>
      <text class="link link--block" @tap="goEditProfile">维护档案 ›</text>
    </CCard>

    <!-- 趋势入口 -->
    <CCard
      title="趋势"
      class="home__card"
      :class="{ 'home__card--dim': userStore.needProfile }"
    >
      <view class="trend">
        <text class="trend__desc">体重 / 缺口 近 7 天走势</text>
        <CButton type="ghost" size="sm" @click="goAccountDetail">查看曲线 ›</CButton>
      </view>
    </CCard>

    <!-- AI 教练卡（Phase 2：次数接 api.getTimes()，入口进 AI 对话页） -->
    <CCard title="AI 教练" class="home__card">
      <text class="ai__line">{{ aiTip1 }}</text>
      <text class="ai__line">{{ aiTip2 }}</text>
      <!-- 剩余次数：加载中 / 失败均有兜底文案，不空白 -->
      <text class="ai__times" :class="{ 'ai__times--zero': aiTimesLeft === 0 }">
        {{ aiTimesText }}
      </text>
      <view class="ai__actions">
        <CButton size="sm" @click="onCoach">问教练</CButton>
        <CButton size="sm" type="secondary" @click="onHunger">饥饿急救</CButton>
      </view>
    </CCard>

    <!-- 快捷服务四宫格（§5.1） -->
    <CCard title="快捷服务" class="home__card">
      <view class="grid">
        <view v-for="item in services" :key="item.label" class="grid__item" @tap="item.action">
          <text class="grid__icon">{{ item.icon }}</text>
          <text class="grid__label">{{ item.label }}</text>
        </view>
      </view>
    </CCard>

    <!-- 券提醒占位（Phase 3 接入券池） -->
    <CCard title="券提醒" class="home__card">
      <view class="coupon">
        <text class="coupon__icon">🎟️</text>
        <text class="coupon__text">券提醒与邀请得券（Phase 3 接入）</text>
      </view>
    </CCard>

    <!-- FAB 拍照按钮（§5.1，直径 120rpx） -->
    <view class="fab" @tap="goCamera">📷</view>
  </view>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { useUserStore } from '@/stores/user'
import { useAccountStore } from '@/stores/account'
import { useToast } from '@/composables/useToast'
import { getTimes } from '@/api/ai'
import { track } from '@/utils/track'
import type { MealSummary } from '@/types/api'

const userStore = useUserStore()
const accountStore = useAccountStore()
const toast = useToast()

/* ---------- 顶部问候 / 日期 ---------- */
const now = new Date()
const greeting = now.getHours() < 12 ? '早上好' : now.getHours() < 18 ? '下午好' : '晚上好'
const todayText = `${now.getMonth() + 1}月${now.getDate()}日 周${'日一二三四五六'[now.getDay()]}`

/* ---------- 数字千分位格式化（小程序 toLocaleString 分组不可靠，手写兜底） ---------- */
function fmt(n: number): string {
  return Math.round(Math.abs(n))
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, ',')
}
function fmtSigned(n: number): string {
  return (n < 0 ? '-' : '') + fmt(n)
}

/* ---------- 热量环（中心 = today_left，不是 tee−intake） ---------- */
const leftText = computed(() => fmtSigned(accountStore.left))
const leftLabel = computed(() => (accountStore.left >= 0 ? '今天还能吃 kcal' : '已超标 kcal'))

const ringColor = computed(() => {
  if (accountStore.overBudget) return '#ef4444' // 超标：危险红
  if (accountStore.percent >= 100) return '#ef4444'
  if (accountStore.percent > 80) return '#f59e0b' // 接近预算：琥珀
  return '#22c55e' // 品牌绿
})

const intake = computed(() => Math.round(accountStore.today?.intake ?? 0))
const burnt = computed(() => Math.round(accountStore.today?.calories_burnt ?? 0))
const deficit = computed(() => Math.round(accountStore.today?.deficit ?? 0))
const steps = computed(() => accountStore.today?.steps ?? 0)

const ACTIVITY_LABEL: Record<number, string> = {
  1: '卧床',
  2: '久坐',
  3: '轻度',
  4: '中度',
  5: '高度',
}
const activityText = computed(() => {
  const level = userStore.profile?.activity_level
  return level ? ACTIVITY_LABEL[level] || '久坐' : '久坐'
})

/* ---------- 摄入明细（按 meal_type 排序 + 中文名） ---------- */
const MEAL_LABEL: Record<number, string> = { 1: '早餐', 2: '午餐', 3: '晚餐', 4: '加餐' }
function mealLabel(m: MealSummary): string {
  return m.name || MEAL_LABEL[m.meal_type] || '其他'
}
const meals = computed(() => {
  const list = accountStore.today?.meals ?? []
  return [...list].sort((a, b) => a.meal_type - b.meal_type)
})
const emptyMealText = computed(() =>
  userStore.needProfile ? '建档后开始记录饮食' : '还没有摄入记录，去记录第一餐吧',
)

/* ---------- 核心指标（档案 + 体重推算；缺失灰显占位） ---------- */
const coreMetrics = computed(() => {
  const p = userStore.profile
  const clamp = (v: number) => Math.min(100, Math.max(0, Math.round(v)))
  if (!p) {
    // 未建档：灰显占位（值空 → 展示 --）
    return [
      { icon: '⚖️', label: '体重', value: '', bar: 0, color: '#3b82f6' },
      { icon: '📊', label: 'BMI', value: '', bar: 0, color: '#3b82f6' },
      { icon: '🔥', label: '基础代谢', value: '', bar: 0, color: '#3b82f6' },
      { icon: '🎯', label: '目标体重', value: '', bar: 0, color: '#9ca3af' },
    ]
  }
  const h = p.height_cm / 100
  const bmi = h > 0 ? p.current_weight / (h * h) : 0
  let bmiColor = '#22c55e'
  if (bmi <= 0) bmiColor = '#9ca3af'
  else if (bmi < 18.5) bmiColor = '#f59e0b'
  else if (bmi >= 28) bmiColor = '#ef4444'
  else if (bmi >= 24) bmiColor = '#f59e0b'
  const bmr = p.bmr || accountStore.today?.bmr || 0
  return [
    {
      icon: '⚖️',
      label: '体重',
      value: `${p.current_weight.toFixed(1)} kg`,
      bar: clamp((p.current_weight / 120) * 100),
      color: '#3b82f6',
    },
    {
      icon: '📊',
      label: 'BMI',
      value: bmi > 0 ? bmi.toFixed(1) : '',
      bar: clamp((bmi / 35) * 100),
      color: bmiColor,
    },
    {
      icon: '🔥',
      label: '基础代谢',
      value: bmr ? `${Math.round(bmr)} kcal` : '',
      bar: clamp((bmr / 2200) * 100),
      color: '#22c55e',
    },
    {
      icon: '🎯',
      label: '目标体重',
      value: p.target_weight != null ? `${p.target_weight.toFixed(1)} kg` : '',
      bar: p.target_weight != null ? clamp((p.target_weight / 120) * 100) : 0,
      color: '#9ca3af',
    },
  ]
})

/* ---------- AI 教练卡：剩余次数（Phase 2 接 api.getTimes()） ---------- */
/** 今日剩余 AI 次数：null=未拉取/拉取失败（兜底文案，不锁入口） */
const aiTimesLeft = ref<number | null>(null)
const aiTimesLoaded = ref(false)

const aiTimesText = computed(() => {
  if (!aiTimesLoaded.value) return 'AI 次数加载中…'
  if (aiTimesLeft.value === null) return 'AI 次数暂不可用'
  if (aiTimesLeft.value === 0) return '今日剩余 0 次，邀请好友解锁'
  return `今日剩余 ${aiTimesLeft.value} 次`
})

async function loadAiTimes() {
  try {
    const data = await getTimes()
    aiTimesLeft.value = data?.times_left ?? null
  } catch (e) {
    // 失败保留 null（文案降级为"暂不可用"），不让卡片空白
    aiTimesLeft.value = null
    void e
  } finally {
    aiTimesLoaded.value = true
  }
}

/* ---------- AI 教练卡文案（Phase 2 前静态占位） ---------- */
const aiTip1 = computed(() => {
  if (userStore.needProfile) return '先完善身体档案，AI 才能给出个性化建议。'
  return accountStore.overBudget
    ? '今天已超出预算，晚点可以散步 20 分钟平衡一下。'
    : '今天热量控制得不错，注意补充蛋白质和蔬菜。'
})
const aiTip2 = computed(() =>
  steps.value < 5000 ? '步数偏少，建议快走 20 分钟提升消耗。' : '今天活动量达标，保持节奏！',
)

/* ---------- 快捷服务 ---------- */
const services = [
  { icon: '🔍', label: 'AI 检测', action: goCamera },
  { icon: '🍽️', label: '吃什么', action: goEat },
  { icon: '📝', label: '记录', action: goRecord },
  { icon: '📅', label: '一键预约', action: () => onPlaceholder('一键预约（Phase 3 接入）') },
  { icon: '🏪', label: '商家比价', action: goMerchant },
  { icon: '👨‍⚕️', label: '教练问诊', action: () => onPlaceholder('教练问诊（Phase 2 接入）') },
]

/* ---------- 生命周期 ---------- */
/** 首次进入首页标记：区分冷启动与从子页返回（app_open 的 from 口径） */
let firstShow = true

onShow(() => {
  if (!userStore.isLogined) {
    uni.reLaunch({ url: '/pages/login/login' })
    return
  }
  // 活跃埋点：进入首页（日活 / 留存判定）
  track('app_open', { from: firstShow ? 'cold_start' : 'back' })
  firstShow = false
  if (!userStore.detail) userStore.fetchMe()
  accountStore.refresh() // 拍照 / 记录返回后刷新账户
  if (!userStore.profileLoaded) userStore.fetchProfile()
  loadAiTimes()
})

/* ---------- 跳转 / 交互 ---------- */
function goEditProfile() {
  uni.navigateTo({ url: '/pages/profile/edit' })
}
function goAccountDetail() {
  uni.navigateTo({ url: '/pages/account/detail' })
}
function goCamera() {
  uni.navigateTo({ url: '/pages/record/camera' })
}
/** 吃什么已是 Tab 页（§3.2），Tab 间跳转须 switchTab（navigateTo 对 tab 页无效） */
function goEat() {
  uni.switchTab({ url: '/pages/eat/eat' })
}
function goFoodList() {
  uni.navigateTo({ url: '/pages/record/food-list' })
}
function goSportAdd() {
  uni.navigateTo({ url: '/pages/record/sport-add' })
}
/** 商家已从 Tab 降为普通页（§3.2），改 navigateTo */
function goMerchant() {
  uni.navigateTo({ url: '/pages/merchant/merchant' })
}
/** 「记录」已从 Tab 降为普通页（§3.2），由首页快捷服务进入 */
function goRecord() {
  uni.navigateTo({ url: '/pages/record/record' })
}
function onPlaceholder(text: string) {
  toast.info({ title: text })
}
/** 【假设】饥饿急救话术在 chat 页实现，首页直接带参跳转复用，避免两处维护 */
function onCoach() {
  uni.navigateTo({ url: '/pages/ai/chat' })
}
function onHunger() {
  uni.navigateTo({ url: '/pages/ai/chat?hunger=1' })
}
</script>

<style lang="scss" scoped>
.home {
  padding: $space-md;
  padding-bottom: calc(#{$space-xl} + 120rpx);
}

.home__header {
  @include flex-between;

  margin-bottom: $space-md;
}

.home__hello {
  display: flex;
  flex-direction: column;
}

.home__greet {
  display: block;
  font-size: $t-32;
  font-weight: 500;
  color: $text-1;
}

.home__date {
  font-size: $t-22;
  color: $text-3;
}

.home__entry {
  @include flex-center;

  height: 56rpx;
  padding: 0 $space-sm;
  background: $card;
  border: 1rpx solid $border;
  border-radius: 999rpx;

  &-text {
    font-size: $t-22;
    color: $brand;
  }

  &-arrow {
    margin-left: 4rpx;
    font-size: $t-22;
    color: $brand;
  }
}

.home__guide {
  margin-bottom: $space-md;
}

.home__card {
  margin-bottom: $space-md;

  // 未建档：其余模块灰显（仍可点击，引导建档）
  &--dim {
    opacity: 0.6;
  }
}

.guide {
  display: flex;
  align-items: center;

  &__icon {
    margin-right: $space-sm;
    font-size: 44rpx;
  }

  &__main {
    flex: 1;
    display: flex;
    flex-direction: column;
  }

  &__title {
    font-size: $t-26;
    font-weight: 500;
    color: $text-1;
  }

  &__desc {
    font-size: $t-22;
    color: $text-3;
  }
}

.link {
  font-size: $t-22;
  color: $brand;

  &--block {
    display: block;
    margin-top: $space-sm;
    text-align: right;
  }
}

.ring-wrap {
  @include flex-center;
}

.ring-center {
  @include flex-center(column);

  &__num {
    font-size: $t-num-lg;
    font-weight: 700;
    color: $text-1;
  }

  &__label {
    font-size: $t-22;
    color: $text-2;
  }
}

.metrics {
  margin-top: $space-lg;

  &__row {
    @include flex-between;

    padding: $space-xs 0;

    &:last-child {
      margin-top: $space-xs;
    }
  }

  &__k {
    font-size: $t-22;
    color: $text-3;
  }

  &__v {
    font-size: $t-26;
    font-weight: 500;
    color: $text-1;

    &--plus {
      color: $info;
    }

    &--danger {
      color: $danger;
    }
  }
}

.calib {
  display: block;
  margin-top: $space-sm;
  font-size: $t-22;
  color: $text-3;
}

.meal-list {
  &__row {
    @include flex-between;

    padding: $space-sm 0;

    &:not(:last-child) {
      @include hairline(bottom);
    }
  }

  &__name {
    font-size: $t-26;
    color: $text-1;
  }

  &__kcal {
    font-size: $t-24;
    color: $text-2;
  }
}

.sport {
  @include flex-between;

  &__item {
    @include flex-center(column);
  }

  &__k {
    font-size: $t-22;
    color: $text-3;
  }

  &__v {
    font-size: $t-num-md;
    font-weight: 700;
    color: $text-1;
  }

  &__actions {
    margin-top: $space-sm;
    display: flex;
    justify-content: flex-end;
  }
}

.core {
  display: flex;
  align-items: center;
  padding: $space-xs 0;

  &__icon {
    width: 44rpx;
    font-size: 34rpx;
  }

  &__label {
    flex: 1;
    font-size: $t-26;
    color: $text-2;
  }

  &__value {
    width: 180rpx;
    font-size: $t-26;
    font-weight: 500;
    color: $text-1;
    text-align: right;

    &--empty {
      color: $text-3;
    }
  }

  &__bar {
    width: 140rpx;
    height: 12rpx;
    margin-left: $space-sm;
    background: $border;
    border-radius: 999rpx;
    overflow: hidden;
  }

  &__bar-fill {
    height: 100%;
    border-radius: 999rpx;
    transition: width $duration-base $ease-out;
  }
}

.trend {
  @include flex-between;

  &__desc {
    font-size: $t-26;
    color: $text-2;
  }
}

.ai {
  &__line {
    display: block;
    font-size: $t-26;
    color: $text-1;
    line-height: 1.6;
  }

  &__times {
    display: block;
    margin-top: $space-xs;
    font-size: $t-22;
    color: $text-3;

    // 次数用尽（06 §1.5 验收项用词一致）
    &--zero {
      color: $danger;
    }
  }

  &__actions {
    display: flex;
    gap: $space-sm;
    margin-top: $space-sm;
  }
}

.grid {
  display: flex;
  flex-wrap: wrap;

  &__item {
    @include flex-center(column);

    width: 25%;
    padding: $space-sm 0;
  }

  &__icon {
    font-size: 48rpx;
  }

  &__label {
    margin-top: $space-xs;
    font-size: $t-22;
    color: $text-2;
  }
}

.coupon {
  display: flex;
  align-items: center;

  &__icon {
    margin-right: $space-sm;
    font-size: 40rpx;
  }

  &__text {
    font-size: $t-24;
    color: $text-3;
  }
}

.fab {
  @include flex-center;

  position: fixed;
  right: $space-lg;
  bottom: calc(#{$space-lg} + env(safe-area-inset-bottom));
  z-index: $z-fab;
  width: 120rpx;
  height: 120rpx;
  font-size: 56rpx;
  background: $brand;
  border-radius: 50%;
  box-shadow: $shadow-lg;
}
</style>
