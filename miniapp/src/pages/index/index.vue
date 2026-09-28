<template>
  <view class="home">
    <!-- 顶部问候 + 评分占位 -->
    <view class="home__header">
      <view>
        <text class="home__greet">{{ greeting }}，{{ userStore.nickname }}</text>
        <text class="home__date">{{ todayText }}</text>
      </view>
      <view class="home__score card" @tap="goAccountDetail">
        <text class="home__score-num">78</text>
        <text class="home__score-label">评分占位</text>
      </view>
    </view>

    <!-- 热量环 -->
    <CCard title="今日热量" class="home__ring-card">
      <template #extra>
        <text class="home__link" @tap="goAccountDetail">详情 →</text>
      </template>
      <view class="home__ring">
        <CSkeleton v-if="accountStore.loading && !accountStore.today" type="card" />
        <CRingProgress v-else :percent="accountStore.percent" :color="ringColor" :size="280" :stroke-width="28">
          <view class="ring-center">
            <text class="ring-center__num">{{ ringCenterNum }}</text>
            <text class="ring-center__label">{{ ringCenterLabel }}</text>
          </view>
        </CRingProgress>
        <view class="home__summary">
          <view class="home__summary-item">
            <text class="home__summary-num">{{ intake }}</text>
            <text class="home__summary-label">已摄入 kcal</text>
          </view>
          <view class="home__summary-item">
            <text class="home__summary-num">{{ burnt }}</text>
            <text class="home__summary-label">运动消耗 kcal</text>
          </view>
          <view class="home__summary-item">
            <text class="home__summary-num">{{ tee }}</text>
            <text class="home__summary-label">预算 TEE kcal</text>
          </view>
        </view>
      </view>
    </CCard>

    <!-- 摄入明细 -->
    <CCard title="摄入明细" class="home__card">
      <template #extra>
        <text class="home__link" @tap="goTab('/pages/record/record')">全部 →</text>
      </template>
      <view v-if="meals.length" class="meal-list">
        <view v-for="(m, i) in meals" :key="i" class="meal-list__row">
          <text class="meal-list__name">{{ m.name }}</text>
          <text class="meal-list__kcal">{{ Math.round(m.calories) }} kcal</text>
        </view>
      </view>
      <CEmpty v-else text="还没有摄入明细" @action="onFab" />
    </CCard>

    <!-- 运动明细 -->
    <CCard title="运动明细" class="home__card">
      <view class="sport-row">
        <text class="sport-row__item">步数 {{ stepsText }} 步</text>
        <text class="sport-row__item">消耗 {{ burnt }} kcal</text>
      </view>
      <CButton type="ghost" size="sm" @click="onPlaceholder('添加运动（P1 接入）')">+ 添加运动</CButton>
    </CCard>

    <!-- 快捷服务宫格 -->
    <CCard title="快捷服务" class="home__card">
      <view class="grid">
        <view v-for="item in services" :key="item.label" class="grid__item" @tap="item.action">
          <text class="grid__icon">{{ item.icon }}</text>
          <text class="grid__label">{{ item.label }}</text>
        </view>
      </view>
    </CCard>

    <!-- FAB 悬浮拍照按钮 -->
    <view class="fab" @tap="onFab">📷</view>
  </view>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { useUserStore } from '@/stores/user'
import { useAccountStore } from '@/stores/account'
import { useToast } from '@/composables/useToast'

const userStore = useUserStore()
const accountStore = useAccountStore()
const toast = useToast()

// 【假设】健康分占位：环色按剩余预算映射（>20% 剩余=品牌绿，0~20%=琥珀，<0=红）
const ringColor = computed(() => {
  if (accountStore.left < 0) return '#ef4444'
  if (accountStore.percent > 80) return '#f59e0b'
  return '#22c55e'
})

const ringCenterNum = computed(() => {
  const left = accountStore.left
  return left >= 0 ? `${left}` : `-${Math.abs(left)}`
})
const ringCenterLabel = computed(() => (accountStore.left >= 0 ? '还能吃 kcal' : '已超标 kcal'))

const intake = computed(() => Math.round(accountStore.today?.intake ?? 0))
const burnt = computed(() => Math.round(accountStore.today?.calories_burnt ?? 0))
const tee = computed(() => Math.round(accountStore.today?.tee ?? 0))
const stepsText = computed(() => (accountStore.today?.steps ?? 0).toLocaleString())
const meals = computed(() => accountStore.today?.meals ?? [])

const now = new Date()
const greeting = now.getHours() < 12 ? '早上好' : now.getHours() < 18 ? '下午好' : '晚上好'
const todayText = `${now.getMonth() + 1}月${now.getDate()}日`

const services = [
  { icon: '📷', label: '拍照记录', action: onFab },
  { icon: '🤖', label: 'AI 教练', action: () => onPlaceholder('AI 教练（P2 接入）') },
  { icon: '🏪', label: '附近商家', action: () => goTab('/pages/merchant/merchant') },
  { icon: '📊', label: '账户详情', action: goAccountDetail },
]

onMounted(() => {
  if (userStore.isLogined) userStore.fetchMe()
})

onShow(() => {
  if (userStore.isLogined) accountStore.fetchToday()
})

function goAccountDetail() {
  uni.navigateTo({ url: '/pages/account/detail' })
}

function goTab(url: string) {
  uni.switchTab({ url })
}

function onPlaceholder(text: string) {
  toast.info({ title: text })
}

function onFab() {
  // 【假设】拍照记录 P1 接入，此处占位
  toast.info({ title: '拍照记录（P1 接入）' })
}
</script>

<style lang="scss" scoped>
.home {
  padding: $space-md;
  padding-bottom: calc(#{$space-xl} + 120rpx);

  &__header {
    @include flex-between;

    margin-bottom: $space-md;
  }

  &__greet {
    display: block;
    font-size: $t-32;
    font-weight: 500;
    color: $text-1;
  }

  &__date {
    font-size: $t-22;
    color: $text-3;
  }

  &__score {
    @include flex-center(column);

    min-width: 120rpx;
    padding: $space-sm $space-md;
  }

  &__score-num {
    font-size: $t-num-md;
    font-weight: 700;
    color: $brand;
  }

  &__score-label {
    font-size: $t-22;
    color: $text-2;
  }

  &__ring-card {
    margin-bottom: $space-md;
  }

  &__link {
    font-size: $t-22;
    color: $brand;
  }

  &__ring {
    @include flex-center(column);
  }

  &__summary {
    @include flex-between;

    width: 100%;
    margin-top: $space-lg;
  }

  &__summary-item {
    @include flex-center(column);
  }

  &__summary-num {
    font-size: $t-num-md;
    font-weight: 700;
    color: $text-1;
  }

  &__summary-label {
    font-size: $t-22;
    color: $text-2;
  }

  &__card {
    margin-bottom: $space-md;
  }
}

.ring-center {
  @include flex-center(column);
}

.ring-center__num {
  font-size: $t-num-lg;
  font-weight: 700;
  color: $text-1;
}

.ring-center__label {
  font-size: $t-22;
  color: $text-2;
}

.meal-list {
  &__row {
    @include flex-between;

    padding: $space-xs 0;
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

.sport-row {
  @include flex-between;

  margin-bottom: $space-sm;

  &__item {
    font-size: $t-26;
    color: $text-1;
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
