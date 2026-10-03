<template>
  <view class="record">
    <!-- 未登录（§5.8 无权限态） -->
    <CNoPermission v-if="!userStore.isLogined" text="登录后查看记录" @action="goLogin" />

    <template v-else>
      <!-- 今日概览（读共享 account store，避免重复拉取） -->
      <CCard title="今日记录" class="record__card">
        <CSkeleton v-if="accountStore.loading && !accountStore.today" type="card" />
        <CError v-else-if="loadError" @retry="reload" />
        <template v-else>
          <view class="record__row">
            <text class="record__label">已摄入</text>
            <text class="record__value">{{ intake }} kcal</text>
          </view>
          <view class="record__row">
            <text class="record__label">运动消耗</text>
            <text class="record__value">{{ burnt }} kcal</text>
          </view>
          <view class="record__row">
            <text class="record__label">步数</text>
            <text class="record__value">{{ stepsText }} 步</text>
          </view>
          <view class="record__row">
            <text class="record__label">今天还能吃</text>
            <text class="record__value" :class="{ 'record__value--danger': left < 0 }">
              {{ left }} kcal
            </text>
          </view>
        </template>
      </CCard>

      <!-- 聚合入口 -->
      <CCard title="快速记录" class="record__card">
        <view class="grid">
          <view v-for="item in entries" :key="item.label" class="grid__item" @tap="item.action">
            <image class="grid__icon" :src="`/static/icons/${item.icon}.png`" mode="aspectFit" />
            <text class="grid__label">{{ item.label }}</text>
          </view>
        </view>
      </CCard>
    </template>
  </view>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { useUserStore } from '@/stores/user'
import { redirectToLogin } from '@/utils/nav'
import { useAccountStore } from '@/stores/account'
import { describeStepsSync, guideToWeRunSetting, syncStepsFromWeRun } from '@/api/records'
import { useToast } from '@/composables/useToast'

const userStore = useUserStore()
const accountStore = useAccountStore()
const toast = useToast()

const loadError = ref(false)
/** 步数同步中（防重复点击） */
const syncing = ref(false)

/* ---------- 数字千分位格式化（小程序 toLocaleString 分组不可靠，手写兜底） ---------- */
function fmt(n: number): string {
  return Math.round(Math.abs(n))
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, ',')
}

const intake = computed(() => Math.round(accountStore.today?.intake ?? 0))
const burnt = computed(() => Math.round(accountStore.today?.calories_burnt ?? 0))
// 剩余额度：统一走 accountStore.left（真值取 today_left，缺失时按 BMR×PAL−摄入+运动−TEF 兜底）
const left = computed(() => accountStore.left)
const stepsText = computed(() => fmt(accountStore.today?.steps ?? 0))

// 聚合入口：拍照识别 / 饮食列表 / 运动 / 步数同步 / 体重
const entries = [
  { icon: 'ic-camera', label: '拍照记录', action: goCamera },
  { icon: 'ic-bowl', label: '饮食记录', action: goFoodList },
  { icon: 'ic-run', label: '运动记录', action: goSport },
  { icon: 'ic-shoe', label: '同步步数', action: onSyncSteps },
  { icon: 'ic-scale', label: '体重记录', action: goWeight },
]

onShow(() => {
  if (userStore.isLogined) reload()
})

function todayStr(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

async function reload() {
  loadError.value = false
  try {
    await accountStore.fetchToday()
  } catch (e) {
    loadError.value = true
  }
}

/**
 * 同步当日步数（F-09）：先预检 scope.werun 授权 → 取微信运动加密数据交后端解密。
 * 提示真源＝后端 steps_source（仅 1 才能说"已同步微信运动 N 步"），未授权/取不到一律说"按活动水平估算"；
 * 未授权时附「去开启微信运动」引导（openSetting），估算值照常入库，不阻断本次流程（§2.4）。
 * 严禁伪造步数常量（原 8000 mock 兜底已移除）。
 */
async function onSyncSteps() {
  if (syncing.value) return
  syncing.value = true
  try {
    const msg = describeStepsSync(await syncStepsFromWeRun(todayStr()))
    toast[msg.tone]({ title: msg.title })
    if (msg.needGuide) guideToWeRunSetting()
    await reload()
  } catch (e) {
    // 错误信息已由 request 封装 toast
  } finally {
    syncing.value = false
  }
}

function goCamera() {
  uni.navigateTo({ url: '/pages/record/camera' })
}
function goFoodList() {
  uni.navigateTo({ url: '/pages/record/food-list' })
}
function goSport() {
  uni.navigateTo({ url: '/pages/record/sport' })
}
function goWeight() {
  uni.navigateTo({ url: '/pages/weight/weight' })
}
function goLogin() {
  redirectToLogin()
}
</script>

<style lang="scss" scoped>
.record {
  padding: $space-md;

  &__card {
    margin-bottom: $space-md;
  }

  &__row {
    @include flex-between;

    padding: $space-xs 0;
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

.grid {
  display: flex;
  flex-wrap: wrap;

  &__item {
    @include flex-center(column);

    width: 25%;
    padding: $space-sm 0;
  }

  &__icon {
    width: 56rpx;
    height: 56rpx;
  }

  &__label {
    margin-top: $space-xs;
    font-size: $t-22;
    color: $text-2;
  }
}
</style>