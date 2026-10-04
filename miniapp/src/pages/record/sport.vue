<template>
  <view class="sport">
    <!-- 未登录（§5.8 无权限态） -->
    <CNoPermission v-if="!userStore.isLogined" text="登录后查看运动记录" @action="goLogin" />

    <template v-else>
      <!-- 今日运动（步数 + 消耗，读共享 account store） -->
      <CCard title="今日运动" class="sport__card">
        <CSkeleton v-if="accountStore.loading && !accountStore.today" type="card" />
        <CError v-else-if="accountError" @retry="loadAccount" />
        <template v-else>
          <view class="sport__stat">
            <view class="sport__stat-item">
              <text class="sport__stat-num">{{ stepsText }}</text>
              <text class="sport__stat-label">步数</text>
            </view>
            <view class="sport__stat-item">
              <text class="sport__stat-num">{{ burnt }}</text>
              <text class="sport__stat-label">消耗 kcal</text>
            </view>
          </view>
          <CButton type="secondary" block :loading="syncing" @click="onSync">同步步数</CButton>
          <!-- 步数来源如实说明（§2.4：取不到按 PAL 估算并提示；未授权时给「去开启微信运动」引导入口，不阻断） -->
          <view v-if="stepsSource" class="sport__source">
            <text class="sport__source-text">{{ stepsSource }}</text>
            <text v-if="stepsGuide" class="sport__source-link" @tap="guideToWeRunSetting">
              去开启微信运动 ›
            </text>
          </view>
        </template>
      </CCard>

      <CCard title="运动记录" class="sport__card">
        <template #extra>
          <picker mode="date" :value="date" @change="onDateChange">
            <text class="sport__date">{{ dateText }} ▾</text>
          </picker>
        </template>

        <CSkeleton v-if="loading" type="line" :rows="3" />
        <CError v-else-if="loadError" @retry="reload" />
        <template v-else>
          <!-- 空态不带按钮：底部常驻「添加运动」主按钮已是入口，避免双按钮 -->
          <CEmpty
            v-if="!sports.length"
            icon="empty-sport"
            text="这一天还没有运动记录"
            button-text=""
          />
          <view v-for="s in sports" :key="s.id" class="sport__item">
            <text class="sport__item-name">{{ s.sport_name || '运动' }}</text>
            <text class="sport__item-sub">{{ s.duration_min }} 分钟 · {{ Math.round(s.calories) }} kcal</text>
          </view>
        </template>
      </CCard>

      <view class="sport__bar">
        <CButton block @click="goAdd">添加运动</CButton>
      </view>
    </template>
  </view>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { useUserStore } from '@/stores/user'
import { redirectToLogin } from '@/utils/nav'
import { useAccountStore } from '@/stores/account'
import { listSports, describeStepsSync, guideToWeRunSetting, syncStepsFromWeRun } from '@/api/records'
import { useToast } from '@/composables/useToast'
import type { SportRecordOut } from '@/types/api'

const userStore = useUserStore()
const accountStore = useAccountStore()
const toast = useToast()

function fmtDate(d = new Date()): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const date = ref(fmtDate())
const dateText = computed(() => {
  const [, m, d] = date.value.split('-')
  return `${Number(m)}月${Number(d)}日`
})

const loading = ref(false)
const loadError = ref(false)
const sports = ref<SportRecordOut[]>([])

const accountError = ref(false)
const syncing = ref(false)
/** 步数来源说明（同步后按后端 steps_source 如实展示；空串=本次会话尚未同步过） */
const stepsSource = ref('')
/** 未授权 scope.werun → 展示「去开启微信运动」引导入口 */
const stepsGuide = ref(false)

/* ---------- 数字千分位格式化（小程序 toLocaleString 分组不可靠，手写兜底） ---------- */
function fmt(n: number): string {
  return Math.round(Math.abs(n))
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, ',')
}

const stepsText = computed(() => fmt(accountStore.today?.steps ?? 0))
const burnt = computed(() => Math.round(accountStore.today?.calories_burnt ?? 0))

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
    const res = await listSports({ date: date.value, page_size: 100 })
    sports.value = res.items
  } catch (e) {
    loadError.value = true
  } finally {
    loading.value = false
  }
}

function onDateChange(e: { detail: { value: string } }) {
  date.value = e.detail.value
  reload()
}

/**
 * 同步当日步数（F-09）：先预检 scope.werun 授权 → 取微信运动加密数据交后端解密。
 * 提示真源＝后端 steps_source（仅 1 才能说"已同步微信运动 N 步"），未授权/取不到一律说"按活动水平估算"。
 * 未授权时给「去开启微信运动」引导（openSetting），估算值照常入库，不阻断本次流程（§2.4）。
 * 严禁伪造步数常量（原 8000 mock 兜底已移除）。
 */
async function onSync() {
  if (syncing.value) return
  syncing.value = true
  try {
    const msg = describeStepsSync(await syncStepsFromWeRun(fmtDate()))
    toast[msg.tone]({ title: msg.title })
    stepsSource.value = msg.sourceLabel
    stepsGuide.value = msg.needGuide
    if (msg.needGuide) guideToWeRunSetting()
    await loadAccount()
  } catch (e) {
    // 错误信息已由 request 封装 toast
  } finally {
    syncing.value = false
  }
}

function goAdd() {
  uni.navigateTo({ url: '/pages/record/sport-add' })
}
function goLogin() {
  redirectToLogin()
}
</script>

<style lang="scss" scoped>
.sport {
  padding: $space-md;

  &__card {
    margin-bottom: $space-md;
  }

  &__stat {
    display: flex;
    margin-bottom: $space-md;
  }

  &__stat-item {
    @include flex-center(column);

    flex: 1;
  }

  &__stat-num {
    font-size: $t-num-md;
    font-weight: 700;
    color: $text-1;
  }

  &__stat-label {
    font-size: $t-22;
    color: $text-2;
  }

  // 步数来源说明 + 未授权引导入口（§2.4 引导开启、不阻断）
  &__source {
    margin-top: $space-sm;
  }

  &__source-text {
    display: block;

    font-size: $t-22;
    color: $text-2;
  }

  &__source-link {
    display: block;

    margin-top: $space-xs;
    font-size: $t-22;
    color: $brand;
  }

  &__date {
    font-size: $t-24;
    color: $brand;
  }

  &__item {
    padding: $space-sm 0;

    &:not(:last-child) {
      @include hairline(bottom);
    }
  }

  &__item-name {
    display: block;
    font-size: $t-26;
    color: $text-1;
  }

  &__item-sub {
    font-size: $t-22;
    color: $text-2;
  }

  &__bar {
    margin-top: $space-md;
    margin-bottom: $space-xl;
  }
}
</style>