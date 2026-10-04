<template>
  <view class="home">
    <!-- 顶部栏（§5.1-1：左「我的体重档案 ▼」进档案 / 未建档显示「立即建档」，右 🔔） -->
    <CTopBar :left-text="profileEntry" @left="goEditProfile" @bell="onNotice" />

    <!-- 未建档引导（§5.1：未建档时首页展示建档引导） -->
    <CCard v-if="userStore.needProfile" class="home__guide">
      <view class="guide">
        <image class="guide__icon" src="/static/icons/ic-doc.png" />
        <view class="guide__main">
          <text class="guide__title">先建档，才能算出今天还能吃多少</text>
          <text class="guide__desc">填写性别 / 身高 / 体重 / 目标，1 分钟搞定</text>
        </view>
        <CButton size="sm" @click="goEditProfile">去建档</CButton>
      </view>
    </CCard>

    <!-- 健康评分卡（§5.1-2）：环形图描边 12rpx + 中心评分 + 状态 + 关注项数 -->
    <CCard
      title="健康评分"
      class="home__card"
      :class="{ 'home__card--dim': userStore.needProfile }"
    >
      <view class="score">
        <CRingProgress
          :percent="healthScore"
          :color="healthColor"
          :size="200"
          :stroke-width="12"
        >
          <view class="score__center">
            <text class="score__num">{{ userStore.needProfile ? '--' : healthScore }}</text>
            <text class="score__label">{{ bmiStatusLabel }}</text>
          </view>
        </CRingProgress>
        <view class="score__side">
          <text class="score__side-title">{{ attentionItems.length }} 项需要关注</text>
          <text class="link" @tap="goEditProfile">查看完整档案 ›</text>
        </view>
      </view>
    </CCard>

    <!-- 需要你关注列表（§5.1-3）：状态点 + 标题 + 数值 + 两个小操作 -->
    <CCard
      v-if="attentionItems.length"
      title="需要你关注"
      class="home__card"
      :class="{ 'home__card--dim': userStore.needProfile }"
    >
      <view v-for="it in attentionItems" :key="it.key" class="att">
        <view class="att__head">
          <view class="att__dot" :style="{ background: it.dot }" />
          <text class="att__title">{{ it.title }}</text>
          <text class="att__value">{{ it.value }}</text>
        </view>
        <view class="att__actions">
          <CButton
            v-for="a in it.actions"
            :key="a.label"
            size="sm"
            :type="a.ghost ? 'ghost' : 'secondary'"
            @click="a.run"
          >
            {{ a.label }}
          </CButton>
        </view>
      </view>
    </CCard>

    <!-- 热量账户环形图（§5.1-4：中心「今天还能吃」= today_left） -->
    <CCard
      title="今日热量"
      class="home__card"
      :class="{ 'home__card--dim': userStore.needProfile }"
    >
      <template #extra>
        <text class="link" @tap="goAccountDetail">详情 ›</text>
      </template>

      <CSkeleton v-if="accountStore.loading && !accountStore.today" type="card" />
      <!-- 未建档优先于错误态：未建档时 GET /api/account/today 返回 404 会置 error，
           不能让 CError 抢在建档引导前（§5.1 要求未建档时显示建档引导卡）。
           profileLoaded 兜住同类竞态：档案没回来之前不渲染错误卡（账户请求也已收口到档案之后，
           见 loadAccountAfterProfile），渲染顺序永远是「引导卡 → 错误卡」。 -->
      <CEmpty
        v-else-if="userStore.needProfile"
        icon="empty-food"
        text="建档后展示今日热量账户"
        button-text="去建档"
        @action="goEditProfile"
      />
      <CError
        v-else-if="accountStore.error && !accountStore.today && userStore.profileLoaded"
        @retry="accountStore.refresh"
      />
      <CEmpty
        v-else-if="!accountStore.today"
        icon="empty-food"
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

        <!-- 运动明细并入本卡（§5.1-6 信息不丢：步数 + 添加运动入口） -->
        <view class="sportline">
          <text class="sportline__text">步数 {{ fmt(steps) }} 步</text>
          <CButton type="ghost" size="sm" @click="goSportAdd">+ 添加运动</CButton>
        </view>
      </template>
    </CCard>

    <!-- 摄入明细（§5.1-5：按餐次汇总） -->
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
      <CEmpty v-else icon="empty-food" :text="emptyMealText" @action="goCamera" />
    </CCard>

    <!-- 核心指标（§5.1-7：只显示有异常的；缺失灰显占位）+ 趋势入口（§5.1-8）+ 自查工具（§5.1-13） -->
    <CCard
      title="核心指标"
      class="home__card"
      :class="{ 'home__card--dim': userStore.needProfile }"
    >
      <view v-for="m in visibleMetrics" :key="m.label" class="core">
        <image class="core__icon" :src="`/static/icons/${m.icon}.png`" mode="aspectFit" />
        <text class="core__label">{{ m.label }}</text>
        <text class="core__value" :class="{ 'core__value--empty': !m.value }">
          {{ m.value || '--' }}
        </text>
        <view class="core__bar">
          <view class="core__bar-fill" :style="{ width: m.bar + '%', background: m.color }" />
        </view>
      </view>
      <text v-if="metricsOk" class="core-ok">各项核心指标正常</text>
      <text class="link link--block" @tap="goEditProfile">维护档案 ›</text>
      <view class="core-foot">
        <text class="core-foot__text">体重 / 缺口 近 7 天走势</text>
        <CButton type="ghost" size="sm" @click="goAccountDetail">查看曲线 ›</CButton>
      </view>
      <view class="core-foot tools">
        <CButton type="secondary" size="sm" @click="onBmiTest">BMI自测</CButton>
        <CButton type="secondary" size="sm" @click="onFatTest">体脂自测</CButton>
        <CButton type="secondary" size="sm" @click="onBmrTest">基础代谢</CButton>
      </view>
    </CCard>

    <!-- AI 教练卡（§5.1-9：次数接 api.getTimes()，入口进 AI 对话页） -->
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

    <!-- 快捷服务四宫格（§5.1-10） -->
    <CCard title="快捷服务" class="home__card">
      <view class="grid">
        <view v-for="item in services" :key="item.label" class="grid__item" @tap="item.action">
          <image class="grid__icon" :src="`/static/icons/${item.icon}.png`" mode="aspectFit" />
          <text class="grid__label">{{ item.label }}</text>
        </view>
      </view>
    </CCard>

    <!-- 券提醒（§5.1-11）：接 /api/coupon/list 真实券；无券时引导邀请（邀请规则新口径无「双方各得券」） -->
    <CCard title="券提醒" class="home__card">
      <view v-if="reminderCoupons.length" class="coupon">
        <view v-for="c in reminderCoupons" :key="c.id" class="coupon__row" @tap="goCoupon">
          <image class="coupon__icon" src="/static/icons/ic-coupon.png" mode="aspectFit" />
          <text class="coupon__name">{{ couponLabel(c) }}</text>
          <text class="coupon__days">{{ daysLeft(c) }} 天后过期</text>
          <text class="coupon__use">去使用 ›</text>
        </view>
      </view>
      <view v-else class="coupon">
        <view class="coupon__row coupon__row--empty">
          <image class="coupon__icon" src="/static/icons/ic-coupon.png" mode="aspectFit" />
          <text class="coupon__name">暂无可用券</text>
        </view>
      </view>
      <view class="coupon__invite" @tap="goInvite">
        <text class="coupon__invite-text">邀请好友解锁更多 AI 次数</text>
        <text class="link">立即邀请 ›</text>
      </view>
    </CCard>

    <!-- 同款减友经验（§5.1-12） -->
    <CCard title="同款减友经验" class="home__card">
      <text class="peer__text">{{ peerTip }}</text>
      <view class="peer__actions">
        <CButton type="ghost" size="sm" @click="goCommunity">查看同款经验 ›</CButton>
      </view>
    </CCard>

    <!-- 最近记录（§5.1-14） -->
    <CCard title="最近记录" class="home__card">
      <template #extra>
        <text class="link" @tap="goFoodList">全部 ›</text>
      </template>
      <view v-if="recentMeal" class="recent" @tap="goFoodList">
        <view class="recent__head">
          <text class="recent__date">{{ recentDate }}</text>
          <text class="recent__meal">{{ mealTypeLabel(recentMeal.meal_type) }}</text>
        </view>
        <text class="recent__food">{{ recentMeal.food_name }}</text>
      </view>
      <CEmpty v-else icon="empty-food" text="还没有记录" button-text="去记录" @action="goCamera" />
    </CCard>

    <!-- FAB 拍照按钮（§5.1-15，直径 120rpx） -->
    <view class="fab" @tap="goCamera">
      <image class="fab__icon" src="/static/icons/ic-camera-white.png" mode="aspectFit" />
    </view>

    <!-- 当日状态选择弹窗（§2.3.1「今天什么状态」五选一；用户不选不阻断，回退默认 PAL） -->
    <view v-if="statusVisible" class="mask" @tap="closeStatus">
      <view class="status" @tap.stop>
        <text class="status__title">今天什么状态？</text>
        <text class="status__desc">选一个当前状态，更准地估算今日消耗（NEAT 粗调）</text>
        <view
          v-for="opt in STATUS_OPTIONS"
          :key="opt.level"
          class="status__opt"
          @tap="onChooseStatus(opt.level)"
        >
          <text class="status__opt-name">{{ opt.name }}</text>
          <text class="status__opt-desc">{{ opt.desc }}</text>
        </view>
        <text class="status__skip" @tap="closeStatus">暂不选择，按档案默认 PAL 估算 ›</text>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { useUserStore } from '@/stores/user'
import { useAccountStore } from '@/stores/account'
import { useToast } from '@/composables/useToast'
import { getTimes } from '@/api/ai'
import { getCoupons } from '@/api/order'
import { listMeals } from '@/api/records'
import { track } from '@/utils/track'
import { redirectToLogin } from '@/utils/nav'
import type { MealSummary, CouponOut, MealRecordOut } from '@/types/api'

const userStore = useUserStore()
const accountStore = useAccountStore()
const toast = useToast()

/* ---------- 顶部栏（§5.1-1：档案入口 + 🔔 占位） ---------- */
const profileEntry = computed(() => (userStore.needProfile ? '立即建档' : '我的体重档案'))
/** 通知占位（消息中心二期接入） */
function onNotice() {
  toast.info({ title: '消息中心后续版本支持' })
}

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

/* ---------- 当日状态选择（§2.3.1「今天什么状态」/ §6.3.3 NEAT 第一层，F-01） ---------- */
/** 五选一：1卧床 2久坐 3轻度 4中度 5高度（与建档 activity_level 同档） */
const STATUS_OPTIONS: { level: 1 | 2 | 3 | 4 | 5; name: string; desc: string }[] = [
  { level: 1, name: '卧床', desc: '几乎不下床 / 生病休养' },
  { level: 2, name: '久坐', desc: '办公室久坐，很少走动' },
  { level: 3, name: '轻度', desc: '日常走动，少量运动' },
  { level: 4, name: '中度', desc: '经常走动或规律运动' },
  { level: 5, name: '高度', desc: '体力劳动或高强度训练' },
]
const statusVisible = ref(false)
/**
 * 【假设】当日仅弹一次：以「日期」去重，用户不选也不在当天重复打扰
 * （§2.3.1「用户不点则用默认 PAL」，故不选即静默回退建档值）。
 */
const STATUS_PROMPT_KEY = 'today_status_prompt_date'

function todayKey(): string {
  const d = new Date()
  return `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`
}

/** 当日首次进入、已建档且未选状态时弹窗；已选或今日已弹过则跳过（不阻断） */
function maybePromptStatus() {
  if (userStore.needProfile) return
  const t = accountStore.today
  if (!t || t.activity_level != null) return
  const key = todayKey()
  if (uni.getStorageSync(STATUS_PROMPT_KEY) === key) return
  uni.setStorageSync(STATUS_PROMPT_KEY, key)
  statusVisible.value = true
}

function closeStatus() {
  statusVisible.value = false
}

/** 选择后写入当日状态并刷新账户；失败仅 toast，不阻断首页 */
async function onChooseStatus(level: 1 | 2 | 3 | 4 | 5) {
  statusVisible.value = false
  try {
    await accountStore.setTodayStatus(level)
    toast.success({ title: '已记录今天的状态' })
  } catch (e) {
    void e // 失败信息已由 request 封装 toast
  }
}

/* ---------- 健康评分卡（§5.1-2）：由 BMI 派生评分与状态 ---------- */
const bmi = computed(() => {
  const p = userStore.profile
  if (!p || p.height_cm <= 0) return 0
  const h = p.height_cm / 100
  return p.current_weight / (h * h)
})
const bmiStatusLabel = computed(() => {
  const v = bmi.value
  if (!v) return '待建档'
  if (v < 18.5) return '偏瘦'
  if (v < 24) return '正常'
  if (v < 28) return '轻度超重'
  return '肥胖'
})
/** 【假设】文档未给评分算法：以 BMI 22 为满分基准，偏离 1 分扣 5 分，钳制 0~100 */
const healthScore = computed(() => {
  if (!bmi.value) return 0
  return Math.min(100, Math.max(0, Math.round(100 - Math.abs(bmi.value - 22) * 5)))
})
/** 评分环颜色（§4.12 健康三色区间：<60 红 / 60-80 琥珀 / >80 绿） */
const healthColor = computed(() => {
  const s = healthScore.value
  if (s < 60) return '#ef4444'
  if (s <= 80) return '#f59e0b'
  return '#22c55e'
})

/* ---------- 券 / 最近记录（§5.1-11 / §5.1-14，真实接口） ---------- */
const coupons = ref<CouponOut[]>([])
const recentMeal = ref<MealRecordOut | null>(null)

const DAY_MS = 24 * 3600 * 1000
/** 剩余可用天数（向上取整，非负） */
function daysLeft(c: CouponOut): number {
  if (!c.valid_to) return 0
  return Math.max(0, Math.ceil((new Date(c.valid_to).getTime() - Date.now()) / DAY_MS))
}
/** 券提醒：未用且带有效期，按到期日升序取前 2 张 */
const reminderCoupons = computed(() =>
  coupons.value
    .filter((c) => c.status === 1 && c.valid_to)
    .sort((a, b) => new Date(a.valid_to || '').getTime() - new Date(b.valid_to || '').getTime())
    .slice(0, 2),
)
/** 即将过期（7 天内）的未用券，升序 */
const expiringCoupons = computed(() =>
  reminderCoupons.value.filter((c) => daysLeft(c) <= 7),
)
const SCOPE_TEXT: Record<number, string> = { 1: '吃', 2: '动', 3: '异业', 4: '通用' }
const TYPE_TEXT: Record<number, string> = { 1: '满减券', 2: '折扣券', 3: '免费券', 4: '体验券' }
/** 【假设】券无名称字段，按「scope·type」拼展示名 */
function couponLabel(c: CouponOut): string {
  return `${SCOPE_TEXT[c.scope] || ''}·${TYPE_TEXT[c.type] || '优惠券'}`
}
const recentDate = computed(() => {
  const d = recentMeal.value?.record_date
  return d && d.length >= 7 ? `${d.slice(0, 4)}.${d.slice(5, 7)}` : ''
})

const MEAL_LABEL: Record<number, string> = { 1: '早餐', 2: '午餐', 3: '晚餐', 4: '加餐' }
function mealTypeLabel(t: number): string {
  return MEAL_LABEL[t] || '其他'
}

async function loadCoupons() {
  try {
    const data = await getCoupons({ status: 1, page_size: 50 })
    coupons.value = data?.items ?? []
  } catch (e) {
    coupons.value = [] // 失败降级为「暂无可用券」，不阻断首页
    void e
  }
}
async function loadRecentMeal() {
  try {
    const data = await listMeals({ page_size: 1 })
    recentMeal.value = data?.items?.[0] ?? null
  } catch (e) {
    recentMeal.value = null
    void e
  }
}

/* ---------- 需要你关注列表（§5.1-3） ---------- */
interface AttentionAction {
  label: string
  ghost?: boolean
  run: () => void
}
interface AttentionItem {
  key: string
  dot: string
  title: string
  value: string
  actions: AttentionAction[]
}
const attentionItems = computed<AttentionItem[]>(() => {
  const items: AttentionItem[] = []
  // 🔴 蛋白质摄入不足 —— 【假设】今日账户无蛋白质字段，按文档示例口径静态展示
  items.push({
    key: 'protein',
    dot: '#ef4444',
    title: '蛋白质摄入不足',
    value: '今日缺口 -15g',
    actions: [
      { label: 'AI诊断', run: goChat },
      { label: '找餐', ghost: true, run: goEat },
    ],
  })
  // 🟡 运动不足 —— 真实：当日步数 < 5000（「连续3天」为文档口径，接口仅给当日 → 【假设】）
  if (steps.value < 5000) {
    items.push({
      key: 'sport',
      dot: '#f59e0b',
      title: '运动不足',
      value: `今日 ${fmt(steps.value)} 步`,
      actions: [
        { label: '去运动', run: goSportTab },
        { label: '查看建议', ghost: true, run: goChat },
      ],
    })
  }
  // 🟢 会员到期 —— 【假设】无会员到期接口，基础版（tier=0）按文档口径提示
  if (userStore.tier === 0) {
    items.push({
      key: 'member',
      dot: '#22c55e',
      title: '会员到期',
      value: '15 天后',
      actions: [{ label: '续费', run: () => onPlaceholder('会员续费即将上线') }],
    })
  }
  // 🔵 复查提醒 —— 【假设】无复查接口，静态提醒
  items.push({
    key: 'review',
    dot: '#3b82f6',
    title: '复查提醒',
    value: '30 天后',
    actions: [{ label: '预约复查', run: () => onPlaceholder('预约复查即将上线') }],
  })
  // 🟠 券即将过期 —— 真实：/api/coupon/list 中 7 天内到期的未用券
  const soon = expiringCoupons.value[0]
  if (soon) {
    items.push({
      key: 'coupon',
      dot: '#f97316',
      title: '券即将过期',
      value: `${daysLeft(soon)} 天后`,
      actions: [{ label: '去使用', run: goCoupon }],
    })
  }
  return items
})

/* ---------- 同款减友经验（§5.1-12） ---------- */
/** 【假设】无对应接口，按文档示例口径静态展示 */
const peerTip = '12 位和你情况相似的减友，8 位坚持记录 + 运动后体重下降'

/* ---------- 摄入明细（按 meal_type 排序 + 中文名） ---------- */
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

/* ---------- 核心指标（档案 + 体重推算；§5.1-7「只显示有异常的」） ---------- */
interface CoreMetric {
  icon: string
  label: string
  value: string
  bar: number
  color: string
  abnormal: boolean
}
const coreMetrics = computed<CoreMetric[]>(() => {
  const p = userStore.profile
  const clamp = (v: number) => Math.min(100, Math.max(0, Math.round(v)))
  if (!p) {
    // 未建档：灰显占位（值空 → 展示 --），全量行配合 home__card--dim 引导建档
    return [
      { icon: 'ic-scale', label: '体重', value: '', bar: 0, color: '#3b82f6', abnormal: true },
      { icon: 'ic-chart', label: 'BMI', value: '', bar: 0, color: '#3b82f6', abnormal: true },
      { icon: 'ic-flame', label: '基础代谢', value: '', bar: 0, color: '#3b82f6', abnormal: true },
      { icon: 'ic-target', label: '目标体重', value: '', bar: 0, color: '#9ca3af', abnormal: true },
    ]
  }
  const bmiVal = bmi.value
  let bmiColor = '#22c55e'
  if (bmiVal <= 0) bmiColor = '#9ca3af'
  else if (bmiVal < 18.5) bmiColor = '#f59e0b'
  else if (bmiVal >= 28) bmiColor = '#ef4444'
  else if (bmiVal >= 24) bmiColor = '#f59e0b'
  // 【假设】异常口径：体重超目标 0.5kg 以上、BMI 落在 [18.5, 24) 之外；其余指标无异常概念不占行
  const overTarget = p.target_weight != null && p.current_weight > p.target_weight + 0.5
  const bmiAbnormal = bmiVal > 0 && (bmiVal < 18.5 || bmiVal >= 24)
  return [
    {
      icon: 'ic-scale',
      label: '体重',
      value: `${p.current_weight.toFixed(1)} kg`,
      bar: clamp((p.current_weight / 120) * 100),
      color: '#3b82f6',
      abnormal: overTarget,
    },
    {
      icon: 'ic-chart',
      label: 'BMI',
      value: bmiVal > 0 ? bmiVal.toFixed(1) : '',
      bar: clamp((bmiVal / 35) * 100),
      color: bmiColor,
      abnormal: bmiAbnormal,
    },
  ]
})
/** 已建档时只展示异常项（§5.1-7）；未建档展示占位行 */
const visibleMetrics = computed(() =>
  userStore.needProfile ? coreMetrics.value : coreMetrics.value.filter((m) => m.abnormal),
)
const metricsOk = computed(() => !userStore.needProfile && !visibleMetrics.value.length)

/* ---------- AI 教练卡：剩余次数（Phase 2 接 api.getTimes()） ---------- */
/** 今日剩余 AI 次数：null=未拉取/拉取失败（兜底文案，不锁入口） */
const aiTimesLeft = ref<number | null>(null)
const aiTimesLoaded = ref(false)

const aiTimesText = computed(() => {
  if (!aiTimesLoaded.value) return 'AI 次数加载中…'
  if (aiTimesLeft.value === null) return 'AI 次数暂不可用'
  if (aiTimesLeft.value === 0) return '今日剩余 0 次，邀请好友解锁'
  if (aiTimesLeft.value < 0) return '今日不限次' // -1=终身版不限次
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

/* ---------- 快捷服务（§5.1-10 四宫格；记录入口在「我的·常用」，吃什么为独立 Tab） ---------- */
const services = [
  { icon: 'ic-robot', label: 'AI 检测', action: goCamera },
  { icon: 'ic-calendar', label: '一键预约', action: () => onPlaceholder('一键预约即将上线') },
  { icon: 'ic-store', label: '商家比价', action: goMerchant },
  { icon: 'ic-gym', label: '教练问诊', action: goCoach },
]

/* ---------- 生命周期 ---------- */
/** 首次进入首页标记：区分冷启动与从子页返回（app_open 的 from 口径） */
let firstShow = true

/**
 * 账户请求收口到「档案就绪」之后（冷启动竞态修复）。
 * 未建档时根本不该发 GET /api/account/today（后端 404 → accountStore.error），
 * 而 needProfile 初值是 false、fetchProfile 是异步的：老写法在档案回来前就把账户请求发出去了，
 * 404 若先落地，首页会先闪一次红色错误卡，才切到建档引导卡（§5.1 要求的是后者）。
 * fetchProfile 内部 catch 一切异常并在 finally 置 profileLoaded，所以这里不会卡住页面：
 * 档案请求失败时 needProfile 保持原值 → 账户请求照旧发出，真故障仍由 CError + toast 呈现。
 */
async function loadAccountAfterProfile() {
  if (!userStore.profileLoaded) await userStore.fetchProfile()
  if (userStore.needProfile) return
  await accountStore.refresh()
  // 刷新账户后按需弹「今天什么状态」（未建档 / 已选 / 今日已弹过则跳过）
  maybePromptStatus()
}

onShow(() => {
  if (!userStore.isLogined) {
    redirectToLogin()
    return
  }
  // 活跃埋点：进入首页（日活 / 留存判定）
  track('app_open', { from: firstShow ? 'cold_start' : 'back' })
  firstShow = false
  if (!userStore.detail) void userStore.fetchMe()
  void loadAccountAfterProfile()
  loadAiTimes()
  loadCoupons()
  loadRecentMeal()
})

/* ---------- 跳转 / 交互 ---------- */
function goEditProfile() {
  uni.navigateTo({ url: '/pages/profile/edit' })
}
function goAccountDetail() {
  uni.navigateTo({ url: '/pages/account' })
}
function goCamera() {
  uni.navigateTo({ url: '/pages/record/camera' })
}
/** 吃什么已是 Tab 页（§3.2），Tab 间跳转须 switchTab（navigateTo 对 tab 页无效） */
function goEat() {
  uni.switchTab({ url: '/pages/eat' })
}
function goFoodList() {
  uni.navigateTo({ url: '/pages/record/food-list' })
}
function goSportAdd() {
  uni.navigateTo({ url: '/pages/record/sport-add' })
}
/** 运动 Tab（§3.2），Tab 间跳转须 switchTab */
function goSportTab() {
  uni.switchTab({ url: '/pages/sport' })
}
/** 社区 Tab（§3.2），Tab 间跳转须 switchTab */
function goCommunity() {
  uni.switchTab({ url: '/pages/community' })
}
function goCoupon() {
  uni.navigateTo({ url: '/pages/coupon' })
}
function goInvite() {
  uni.navigateTo({ url: '/pages/invite' })
}
/** 商家已从 Tab 降为普通页（§3.2），改 navigateTo */
function goMerchant() {
  uni.navigateTo({ url: '/pages/merchant/merchant' })
}
function onPlaceholder(text: string) {
  toast.info({ title: text })
}
/** 【假设】饥饿急救话术在 chat 页实现，首页直接带参跳转复用，避免两处维护 */
function goChat() {
  uni.navigateTo({ url: '/pages/ai/chat' })
}
function onCoach() {
  goChat()
}
/** 教练问诊（G1）：真人教练工单对话页（未订阅时页内灰显引导开通） */
function goCoach() {
  uni.navigateTo({ url: '/pages/coach/chat' })
}
function onHunger() {
  uni.navigateTo({ url: '/pages/ai/chat?hunger=1' })
}

/* ---------- 自查工具（§5.1-13） ---------- */
function onBmiTest() {
  if (!userStore.profile) {
    toast.info({ title: '先完善身体档案再自测' })
    return
  }
  uni.showModal({
    title: 'BMI 自测',
    content: `你的 BMI 为 ${bmi.value.toFixed(1)}（${bmiStatusLabel.value}）`,
    showCancel: false,
  })
}
function onFatTest() {
  const p = userStore.profile
  if (!p) {
    toast.info({ title: '先完善身体档案再自测' })
    return
  }
  // 【假设】文档未给体脂算法：用 Deurenberg 公式估算；缺出生年按 30 岁
  const age = p.birth_year ? new Date().getFullYear() - p.birth_year : 30
  const sex = p.gender === 2 ? 0 : 1
  const fat = 1.2 * bmi.value + 0.23 * age - 5.4 - 10.8 * sex
  uni.showModal({
    title: '体脂自测',
    content: `预估体脂率 ${Math.max(0, fat).toFixed(1)}%（Deurenberg 公式估算）`,
    showCancel: false,
  })
}
function onBmrTest() {
  if (!userStore.profile) {
    toast.info({ title: '先完善身体档案再自测' })
    return
  }
  const bmr = userStore.profile.bmr || accountStore.today?.bmr || 0
  uni.showModal({
    title: '基础代谢',
    content: `你的基础代谢约 ${Math.round(bmr)} kcal`,
    showCancel: false,
  })
}
</script>

<style lang="scss" scoped>
.home {
  padding: $space-md;
  padding-bottom: calc(#{$space-xl} + 120rpx);
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
    width: 48rpx;
    height: 48rpx;
    margin-right: $space-sm;
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

/* 健康评分卡 */
.score {
  display: flex;
  align-items: center;

  &__center {
    @include flex-center(column);
  }

  &__num {
    font-size: $t-num-lg;
    font-weight: 700;
    color: $text-1;
  }

  &__label {
    font-size: $t-22;
    color: $text-2;
  }

  &__side {
    flex: 1;
    display: flex;
    flex-direction: column;
    margin-left: $space-lg;
  }

  &__side-title {
    margin-bottom: $space-xs;
    font-size: $t-26;
    color: $text-1;
  }
}

/* 需要你关注 */
.att {
  padding: $space-sm 0;

  &:not(:last-child) {
    @include hairline(bottom);
  }

  &__head {
    display: flex;
    align-items: center;
  }

  &__dot {
    width: 14rpx;
    height: 14rpx;
    margin-right: $space-sm;
    border-radius: 50%;
  }

  &__title {
    flex: 1;
    font-size: $t-26;
    color: $text-1;
  }

  &__value {
    font-size: $t-24;
    color: $text-2;
  }

  &__actions {
    display: flex;
    justify-content: flex-end;
    gap: $space-sm;
    margin-top: $space-xs;
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

/* 运动明细并入今日热量卡后的步数行（§5.1-6） */
.sportline {
  @include flex-between;

  margin-top: $space-sm;
  padding-top: $space-sm;

  @include hairline(top);

  &__text {
    font-size: $t-24;
    color: $text-2;
  }
}

.core-ok {
  display: block;
  font-size: $t-24;
  color: $text-3;
}

/* 核心指标卡内的趋势入口（§5.1-8）与自查工具（§5.1-13）行 */
.core-foot {
  @include flex-between;

  margin-top: $space-sm;
  padding-top: $space-sm;

  @include hairline(top);

  &__text {
    font-size: $t-24;
    color: $text-2;
  }
}

.core {
  display: flex;
  align-items: center;
  padding: $space-xs 0;

  &__icon {
    width: 40rpx;
    height: 40rpx;
    margin-right: $space-xs;
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
    width: 56rpx;
    height: 56rpx;
  }

  &__label {
    margin-top: $space-xs;
    font-size: $t-22;
    color: $text-2;
  }
}

.coupon {
  display: flex;
  flex-direction: column;

  &__row {
    display: flex;
    align-items: center;
    padding: $space-xs 0;

    &--empty {
      color: $text-3;
    }
  }

  &__icon {
    width: 36rpx;
    height: 36rpx;
    margin-right: $space-xs;
  }

  &__name {
    flex: 1;
    font-size: $t-24;
    color: $text-1;
  }

  &__days {
    margin-right: $space-sm;
    font-size: $t-22;
    color: $warn;
  }

  &__use {
    font-size: $t-22;
    color: $brand;
  }

  &__invite {
    @include flex-between;

    margin-top: $space-sm;
    padding-top: $space-sm;

    @include hairline(top);
  }

  &__invite-text {
    font-size: $t-24;
    color: $text-2;
  }
}

.peer {
  &__text {
    display: block;
    font-size: $t-26;
    color: $text-1;
    line-height: 1.6;
  }

  &__actions {
    display: flex;
    justify-content: flex-end;
    margin-top: $space-xs;
  }
}

.tools {
  display: flex;
  gap: $space-sm;

  .c-btn {
    flex: 1;
  }
}

.recent {
  &__head {
    display: flex;
    align-items: center;
    margin-bottom: 4rpx;
  }

  &__date {
    margin-right: $space-xs;
    font-size: $t-22;
    color: $text-3;
  }

  &__meal {
    font-size: $t-22;
    color: $text-2;
  }

  &__food {
    font-size: $t-26;
    color: $text-1;
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
  background: $brand;
  border-radius: 50%;
  box-shadow: $shadow-lg;

  &__icon {
    width: 56rpx;
    height: 56rpx;
  }
}

/* 当日状态选择弹窗（mask + 对话框，沿用既有弹层风格） */
.mask {
  @include flex-center;

  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  left: 0;
  z-index: $z-mask;
  background: $mask;
}

.status {
  z-index: $z-dialog;
  width: 620rpx;
  padding: $space-lg;
  background: $card;
  border-radius: $radius-lg;
  box-shadow: $shadow-lg;

  &__title {
    display: block;
    font-size: $t-32;
    font-weight: 500;
    color: $text-1;
  }

  &__desc {
    display: block;
    margin-top: $space-xs;
    font-size: $t-22;
    color: $text-3;
  }

  &__opt {
    display: flex;
    align-items: baseline;
    margin-top: $space-sm;
    padding: $space-sm $space-md;
    background: $bg;
    border: 1rpx solid $border;
    border-radius: $radius;

    &-name {
      width: 120rpx;
      font-size: $t-28;
      font-weight: 500;
      color: $text-1;
    }

    &-desc {
      flex: 1;
      font-size: $t-22;
      color: $text-3;
    }
  }

  &__skip {
    display: block;
    margin-top: $space-md;
    font-size: $t-22;
    color: $brand;
    text-align: center;
  }
}
</style>