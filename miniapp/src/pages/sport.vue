<template>
  <view class="sport-tab">
    <!-- 顶部栏：标题 + 通知占位（§5.3 顶部；消息二期接入） -->
    <view class="sport-tab__bar">
      <text class="sport-tab__title">运动</text>
      <view class="sport-tab__bell" @tap="onNotice">
        <image class="sport-tab__bell-icon" src="/static/icons/ic-bell.png" mode="aspectFit" />
      </view>
    </view>

    <!-- 未登录（§5.8 无权限态） -->
    <CNoPermission v-if="!userStore.isLogined" text="登录后查看运动数据" @action="goLogin" />

    <template v-else>
      <!-- 1. 今日运动：步数 + 消耗 + 同步（§5.3-1） -->
      <CCard title="今日运动" class="sport-tab__card">
        <CSkeleton v-if="accountStore.loading && !accountStore.today" type="card" />
        <CError v-else-if="accountError" @retry="loadAccount" />
        <template v-else>
          <view class="stat">
            <view class="stat__item">
              <text class="stat__num">{{ fmt(accountStore.today?.steps ?? 0) }}</text>
              <text class="stat__label">步数</text>
            </view>
            <view class="stat__item">
              <text class="stat__num">{{ burnt }}</text>
              <text class="stat__label">消耗 kcal</text>
            </view>
          </view>
          <CButton type="secondary" block :loading="syncing" @click="onSync">同步步数</CButton>
        </template>
      </CCard>

      <!-- 2. AI 建议：吃多后运动强提醒（§5.3-2，仅超标时出现） -->
      <CCard v-if="excess > 0" title="AI 建议" class="sport-tab__card">
        <text class="advice__text">
          今天吃多了 {{ excess }} kcal，建议{{ advice.name }} {{ advice.min }} 分钟，
          你选哪个？
        </text>
        <view class="advice__actions">
          <CButton size="sm" :loading="addingName === advice.name" @click="onQuickAdd(advice)">
            {{ advice.name }}
          </CButton>
          <CButton
            size="sm"
            type="secondary"
            :loading="addingName === altAdvice.name"
            @click="onQuickAdd(altAdvice)"
          >
            {{ altAdvice.name }}
          </CButton>
          <CButton size="sm" type="ghost" @click="onSwitchAdvice">换一个</CButton>
        </view>
      </CCard>

      <!-- 3. 运动记录（今日）+ 添加运动（§5.3-3/4/5，标准项目见添加页） -->
      <CCard title="运动记录" class="sport-tab__card">
        <template #extra>
          <text class="sport-tab__link" @tap="goSportRecords">全部记录 ›</text>
        </template>
        <CSkeleton v-if="loading" type="line" :rows="3" />
        <CError v-else-if="loadError" @retry="reload" />
        <template v-else>
          <CEmpty
            v-if="!sports.length"
            icon="empty-sport"
            text="今天还没有运动记录"
            button-text="添加运动"
            @action="goAdd"
          />
          <view v-for="s in sports" :key="s.id" class="rec">
            <text class="rec__name">{{ s.sport_name || '运动' }}</text>
            <text class="rec__sub">{{ s.duration_min }} 分钟 · {{ Math.round(s.calories) }} kcal</text>
          </view>
          <CButton class="sport-tab__add" type="ghost" size="sm" @click="goAdd">+ 添加运动</CButton>
        </template>
      </CCard>

      <!-- 4. 周期管理（§5.3-7，跳转挑战赛页 §5.6） -->
      <CCard title="周期管理" class="sport-tab__card">
        <view class="plan">
          <text class="plan__desc">21 天挑战 / 90 天计划</text>
          <CButton type="ghost" size="sm" @click="goChallenge">查看详情 ›</CButton>
        </view>
      </CCard>

      <!-- 5. 附近运动场馆（§5.3-6，商家列表页已含健身房类目筛选） -->
      <CCard title="附近场馆" class="sport-tab__card">
        <view class="plan">
          <text class="plan__desc">羽毛球 / 游泳 / 健身房 / 瑜伽，标准项目比价</text>
          <CButton type="ghost" size="sm" @click="goMerchants">查看附近场馆 ›</CButton>
        </view>
      </CCard>
    </template>
  </view>
</template>

<script setup lang="ts">
/**
 * FE · 运动 Tab（/pages/sport）— 文档蓝图对齐
 * 依据：docs/split/01 §3.1 #12（步数、AI 建议、运动记录、标准项目、场馆）
 *      docs/split/03 §5.3（原型图 + 交互）、§5.6（周期管理 → 挑战赛页）
 * 【假设】聚合现有能力最简实现：
 *   - 步数/消耗复用 account store；同步调 syncStepsFromWeRun（优先真实微信运动，取不到按 PAL 估算）；
 *   - AI 建议仅超标时展示（§5.3「吃多后运动强提醒」），一键写入走 createSport；
 *   - 运动列表仅今日，历史日期切换见 /pages/record/sport；
 *   - 标准运动项目在添加运动页（sport-add）内选择，此处给入口；
 *   - 场馆复用商家列表页（健身房类目）；周期管理跳挑战赛页；
 *   - 硬件同步（§5.3-8）无后端支撑，本期不实现。
 */
import { computed, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { useUserStore } from '@/stores/user'
import { redirectToLogin } from '@/utils/nav'
import { useAccountStore } from '@/stores/account'
import { createSport, listSports, syncStepsFromWeRun } from '@/api/records'
import { useToast } from '@/composables/useToast'
import type { SportRecordOut } from '@/types/api'

const userStore = useUserStore()
const accountStore = useAccountStore()
const toast = useToast()

/* ---------- 数字千分位格式化（小程序 toLocaleString 分组不可靠，手写兜底） ---------- */
function fmt(n: number): string {
  return Math.round(Math.abs(n))
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, ',')
}

function todayStr(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/* ---------- 今日运动（步数 / 消耗 / 同步） ---------- */
const accountError = ref(false)
const syncing = ref(false)
const burnt = computed(() => Math.round(accountStore.today?.calories_burnt ?? 0))

/** 超标量 = 「吃多了多少」=-left（left 为负表示超标，§5.1 today_left 口径） */
const excess = computed(() => (accountStore.overBudget ? Math.round(-accountStore.left) : 0))

/* ---------- AI 建议（吃多后强提醒）：两档建议轮换 ---------- */
const ADVICES = [
  { name: '快走', min: 30 },
  { name: '跳绳', min: 10 },
] as const
const adviceIndex = ref(0)
const advice = computed(() => ADVICES[adviceIndex.value % ADVICES.length])
const altAdvice = computed(() => ADVICES[(adviceIndex.value + 1) % ADVICES.length])
const addingName = ref('')

/* ---------- 今日运动记录 ---------- */
const loading = ref(false)
const loadError = ref(false)
const sports = ref<SportRecordOut[]>([])

onShow(() => {
  if (!userStore.isLogined) return
  loadAccount()
  reload()
})

async function loadAccount() {
  accountError.value = false
  try {
    await accountStore.fetchToday()
  } catch (e) {
    accountError.value = true
  }
}

async function reload() {
  loading.value = true
  loadError.value = false
  try {
    const res = await listSports({ date: todayStr(), page_size: 100 })
    sports.value = res.items
  } catch (e) {
    loadError.value = true
  } finally {
    loading.value = false
  }
}

/**
 * 同步当日步数（F-09）：优先真实微信运动数据，取不到则报 0 → 后端按 PAL 估算。
 * 严禁伪造步数常量（原 8000 mock 兜底已移除）。
 */
async function onSync() {
  if (syncing.value) return
  syncing.value = true
  try {
    const { data, gotWeRunData } = await syncStepsFromWeRun(todayStr())
    if (gotWeRunData) {
      toast.success({ title: `同步成功，校准 +${Math.round(data.delta_calories)} kcal` })
    } else {
      toast.info({ title: '未获取到步数，已按活动水平估算' })
    }
    await loadAccount()
  } catch (e) {
    // 错误信息已由 request 封装 toast
  } finally {
    syncing.value = false
  }
}

/** AI 建议一键写入运动记录（MET 由后端按名称映射，同 sport-add 口径） */
async function onQuickAdd(item: { name: string; min: number }) {
  if (addingName.value) return
  addingName.value = item.name
  try {
    await createSport({ sport_name: item.name, duration_min: item.min })
    toast.success({ title: `已记录 ${item.name} ${item.min} 分钟` })
    await Promise.all([reload(), loadAccount()])
  } catch (e) {
    // 错误信息已由 request 封装 toast
  } finally {
    addingName.value = ''
  }
}

function onSwitchAdvice() {
  adviceIndex.value += 1
}

/* ---------- 跳转 ---------- */
function goAdd() {
  uni.navigateTo({ url: '/pages/record/sport-add' })
}
function goSportRecords() {
  uni.navigateTo({ url: '/pages/record/sport' })
}
function goChallenge() {
  uni.navigateTo({ url: '/pages/community/challenge' })
}
function goMerchants() {
  uni.navigateTo({ url: '/pages/merchant/merchant' })
}
function goLogin() {
  redirectToLogin()
}
/** 通知占位（二期接入消息中心，与吃什么页口径一致） */
function onNotice() {
  toast.info({ title: '消息中心后续版本支持' })
}
</script>

<style lang="scss" scoped>
.sport-tab {
  padding: $space-md;
  padding-bottom: calc(#{$space-xl} + env(safe-area-inset-bottom));

  &__bar {
    @include flex-between;

    margin-bottom: $space-md;
  }

  &__title {
    font-size: $t-32;
    font-weight: 500;
    color: $text-1;
  }

  &__bell {
    @include flex-center;
    @include press;

    width: 64rpx;
    height: 64rpx;
    border-radius: 50%;
    background: $card;
    box-shadow: $shadow;
  }

  &__bell-icon {
    width: 36rpx;
    height: 36rpx;
  }

  &__card {
    margin-bottom: $space-md;
  }

  &__link {
    font-size: $t-22;
    color: $brand;
  }

  &__add {
    margin-top: $space-sm;
    align-self: flex-end;
  }
}

// 今日运动两列数值（同运动记录页 stat 口径）
.stat {
  display: flex;
  margin-bottom: $space-md;

  &__item {
    @include flex-center(column);

    flex: 1;
  }

  &__num {
    font-size: $t-num-md;
    font-weight: 700;
    color: $text-1;
  }

  &__label {
    font-size: $t-22;
    color: $text-2;
  }
}

// AI 建议（§5.3-2）
.advice {
  &__text {
    display: block;
    font-size: $t-26;
    color: $text-1;
    line-height: 1.6;
  }

  &__actions {
    display: flex;
    gap: $space-sm;
    margin-top: $space-sm;
  }
}

// 运动记录行（同 record/sport 列表样式）
.rec {
  padding: $space-sm 0;

  &:not(:last-of-type) {
    @include hairline(bottom);
  }

  &__name {
    display: block;
    font-size: $t-26;
    color: $text-1;
  }

  &__sub {
    font-size: $t-22;
    color: $text-2;
  }
}

// 周期管理 / 附近场馆行
.plan {
  @include flex-between;

  &__desc {
    flex: 1;
    font-size: $t-26;
    color: $text-2;
  }
}
</style>
