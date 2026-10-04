<template>
  <view class="sport-tab">
    <!-- 顶部栏（§5.3 顶部：标题 + 🔔；消息二期接入） -->
    <CTopBar title="运动" @bell="onNotice" />

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
          <!-- 步数来源如实说明（§2.4：取不到按 PAL 估算并提示；未授权时给「去开启微信运动」引导入口，不阻断） -->
          <view v-if="stepsSource" class="sport-tab__source">
            <text class="sport-tab__source-text">{{ stepsSource }}</text>
            <text v-if="stepsGuide" class="sport-tab__source-link" @tap="guideToWeRunSetting">
              去开启微信运动 ›
            </text>
          </view>
        </template>
      </CCard>

      <!-- 2. 近 31 天步数曲线（数据源 GET /api/steps/trend）
           CLineChart 纯 view 折线（同 account.vue，不引图表库）；峰值步数直接标在图上。
           后端不补零 → 缺记录的日子断线不画点，绝不当 0 步。 -->
      <CCard :title="trendTitle" class="sport-tab__card">
        <template #extra>
          <text v-if="trendCovered" class="sport-tab__hint">
            已记录 {{ trendCovered }}/{{ STEPS_TREND_MAX_DAYS }} 天
          </text>
        </template>

        <!-- §5.8 四态：骨架屏 / 错误+重试 / 空态引导 / 曲线 -->
        <CSkeleton v-if="trendLoading && !trendLoaded" type="line" :rows="4" />
        <CError v-else-if="trendError && !trendLoaded" @retry="fetchTrend" />
        <CEmpty
          v-else-if="!trendCovered"
          icon="empty-sport"
          text="还没有步数记录，同步微信运动后生成曲线"
          button-text="同步步数"
          @action="onSync"
        />
        <template v-else>
          <view class="trend__legend">
            <view class="trend__key"><view class="trend__mark trend__mark--line" />有记录</view>
            <view class="trend__key"><view class="trend__mark trend__mark--zero" />0 步</view>
            <view class="trend__key"><view class="trend__mark trend__mark--none" />未同步</view>
          </view>
          <CLineChart
            :points="trendPoints"
            color="#22c55e"
            :height="280"
            :min="0"
            mark-peak
            :format-value="fmtPeakSteps"
          />
        </template>
      </CCard>

      <!-- 3. AI 建议：吃多后运动强提醒（§5.3-2，仅超标时出现） -->
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

      <!-- 4. 运动记录（今日）+ 添加运动（§5.3-3/4/5，标准项目见添加页） -->
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
          <!-- 空态由 CEmpty 自带「添加运动」按钮，此入口只在有记录时出现，避免双按钮 -->
          <CButton
            v-if="sports.length"
            class="sport-tab__add"
            type="ghost"
            size="sm"
            @click="goAdd"
          >
            + 添加运动
          </CButton>
        </template>
      </CCard>

      <!-- 5. 周期管理（§5.3-7，跳转挑战赛页 §5.6） -->
      <CCard title="周期管理" class="sport-tab__card">
        <view class="plan">
          <text class="plan__desc">21 天挑战 / 90 天计划</text>
          <CButton type="ghost" size="sm" @click="goChallenge">查看详情 ›</CButton>
        </view>
      </CCard>

      <!-- 6. 附近运动场馆（§5.3-6，商家列表页已含健身房类目筛选） -->
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
 *   - 步数/消耗复用 account store；同步先预检 scope.werun 授权再取微信运动数据，
 *     提示文案以后端 steps_source 为真源（仅 1 才宣称真实步数），未授权只引导开启不阻断（§2.4）；
 *   - 今日运动下方补「近 31 天步数曲线」（数据源 /api/steps/trend），同 account.vue 用 CLineChart
 *     纯 view 折线，不引图表库，峰值步数直接标在图上；点「同步步数」成功后与 onShow 一并重拉曲线；
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
import {
  createSport,
  describeStepsSync,
  getStepsTrend,
  guideToWeRunSetting,
  listSports,
  STEPS_TREND_MAX_DAYS,
  syncStepsFromWeRun,
} from '@/api/records'
import { useToast } from '@/composables/useToast'
import type { SportRecordOut, StepTrendItem } from '@/types/api'

const userStore = useUserStore()
const accountStore = useAccountStore()
const toast = useToast()

/* ---------- 数字千分位格式化（小程序 toLocaleString 分组不可靠，手写兜底） ---------- */
function fmt(n: number): string {
  return Math.round(Math.abs(n))
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, ',')
}

/** 本地时区 YYYY-MM-DD（toISOString 是 UTC，UTC+8 凌晨会错切一天，与 api/account.ts 同口径） */
function fmtDay(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function todayStr(): string {
  return fmtDay(new Date())
}

/* ---------- 今日运动（步数 / 消耗 / 同步） ---------- */
const accountError = ref(false)
const syncing = ref(false)
/** 步数来源说明（同步后按后端 steps_source 如实展示；空串=本次会话尚未同步过） */
const stepsSource = ref('')
/** 未授权 scope.werun → 展示「去开启微信运动」引导入口 */
const stepsGuide = ref(false)
const burnt = computed(() => Math.round(accountStore.today?.calories_burnt ?? 0))

/** 超标量 = 「吃多了多少」=-left（left 为负表示超标，§5.1 today_left 口径） */
const excess = computed(() => (accountStore.overBudget ? Math.round(-accountStore.left) : 0))

/* ---------- 近 31 天步数曲线（/api/steps/trend · CLineChart 纯 view 折线，不引图表库） ---------- */

/** 横轴标签密度：每 5 天出一个（从今日往前数，今日必出）——31 个标签排不下，其余留空 */
const TREND_LABEL_EVERY = 5

const trendItems = ref<StepTrendItem[]>([])
const trendLoading = ref(false)
const trendError = ref(false)
/** 本次会话是否成功拿到过曲线数据（拿到过之后刷新失败只提示不清图，与 account.vue 同口径） */
const trendLoaded = ref(false)

const trendTitle = computed(() => `近 ${STEPS_TREND_MAX_DAYS} 天步数`)

/**
 * items → 连续 STEPS_TREND_MAX_DAYS 个折线点（今日往前推，本地时区）。
 * 三态映射（后端不补零 ⇒ 缺记录 ≠ 0 步，必须分开）：
 * - 有记录且 >0：折线点（区间峰值由组件放大标记并浮出步数）
 * - 有记录且 =0：基线上的点（"今天没走路"是事实）
 * - 后端没返回该日：null → 断线不画点，不参与归一、绝不冒充 0 步
 * 窗口外的记录一律忽略；非法条目（日期非字符串 / 步数非有限数 / 负数）直接丢弃。
 */
const trendPoints = computed<{ label?: string; value: number | null }[]>(() => {
  const byDate = new Map<string, number>()
  for (const it of trendItems.value) {
    const date = typeof it?.date === 'string' ? it.date.slice(0, 10) : ''
    const raw = it?.steps
    const value = typeof raw === 'number' && Number.isFinite(raw) && raw >= 0 ? Math.round(raw) : null
    if (date && value !== null) byDate.set(date, value)
  }

  const today = new Date()
  const points: { label?: string; value: number | null }[] = []
  for (let back = STEPS_TREND_MAX_DAYS - 1; back >= 0; back -= 1) {
    const d = new Date(today)
    d.setDate(d.getDate() - back)
    const key = fmtDay(d)
    points.push({
      label: back % TREND_LABEL_EVERY === 0 ? key.slice(5) : undefined,
      value: byDate.get(key) ?? null,
    })
  }
  return points
})

/** 有记录的天数（真实折线点 + 零点），既作空态判据也作「已记录 N/31 天」文案 */
const trendCovered = computed(() => trendPoints.value.filter((p) => p.value !== null).length)

/** 峰值标签文案：千分位 + 步 */
function fmtPeakSteps(v: number): string {
  return `${fmt(v)} 步`
}

/**
 * 拉取步数曲线。
 * 失败 → 错误态 + 重试；成功但无记录 → 空态引导「同步微信运动后生成曲线」；
 * 两种情况都不画假柱子（后端不补零，前端也不补）。
 */
async function fetchTrend() {
  trendLoading.value = true
  trendError.value = false
  try {
    const data = await getStepsTrend(STEPS_TREND_MAX_DAYS)
    trendItems.value = Array.isArray(data?.items) ? data.items : []
    trendLoaded.value = true
  } catch (e) {
    trendError.value = true
  } finally {
    trendLoading.value = false
  }
}

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
  fetchTrend()
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
 * 同步当日步数（F-09）：先预检 scope.werun 授权 → 取微信运动加密数据交后端解密。
 * 提示真源＝后端 steps_source（仅 1 才能说"已同步微信运动 N 步"），未授权/取不到一律说"按活动水平估算"；
 * backfilled_days>0 的「已回填最近 M 天历史」措辞同样由 describeStepsSync 生成（文案单一真源）。
 * 同步返回后重拉今日账户 + 步数曲线（回填的历史只有曲线能看出来）。
 * 未授权时给「去开启微信运动」引导（openSetting），估算值照常入库，不阻断本次流程（§2.4）。
 * 严禁伪造步数常量（原 8000 mock 兜底已移除）。
 */
async function onSync() {
  if (syncing.value) return
  syncing.value = true
  try {
    const msg = describeStepsSync(await syncStepsFromWeRun(todayStr()))
    toast[msg.tone]({ title: msg.title })
    stepsSource.value = msg.sourceLabel
    stepsGuide.value = msg.needGuide
    if (msg.needGuide) guideToWeRunSetting()
    await Promise.all([loadAccount(), fetchTrend()])
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

  &__card {
    margin-bottom: $space-md;
  }

  &__link {
    font-size: $t-22;
    color: $brand;
  }

  // 曲线卡右上「已记录 N/31 天」：只数后端真有记录的日子（缺失的日子不算）
  &__hint {
    font-size: $t-22;
    color: $text-3;
  }

  &__add {
    margin-top: $space-sm;
    align-self: flex-end;
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

// 近 31 天步数曲线图例（CLineChart 折线：有记录=折线色样 / 0 步=基线实心点 / 未同步=断线）
.trend {
  &__legend {
    display: flex;
    gap: $space-md;
    margin-bottom: $space-sm;
  }

  &__key {
    display: flex;
    align-items: center;

    font-size: $t-22;
    color: $text-2;
  }

  &__mark {
    margin-right: $space-xs;
    background: $brand;

    // 折线色样
    &--line {
      width: 28rpx;
      height: 6rpx;
      border-radius: 3rpx;
    }

    // 0 步：基线上的实心点
    &--zero {
      width: 12rpx;
      height: 12rpx;
      border-radius: 50%;
    }

    // 该日后端没返回＝未同步：虚线空心圆（折线上表现为断线）
    &--none {
      box-sizing: border-box;
      width: 14rpx;
      height: 14rpx;
      border: 2rpx dashed $border;
      border-radius: 50%;
      background: transparent;
    }
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
