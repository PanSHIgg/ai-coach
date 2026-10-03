<template>
  <view class="coupon-list">
    <!-- 1. 分组 tabs：全部 / 吃 / 动 / 异业 / 已失效（含被订单占用、已作废） -->
    <view class="coupon-list__tabs">
      <text
        v-for="t in TABS"
        :key="t.key"
        class="coupon-list__tab"
        :class="{ 'coupon-list__tab--active': activeTab === t.key }"
        @tap="switchTab(t.key)"
      >
        {{ t.label }}
      </text>
    </view>

    <!-- 2. Mock 兜底标注 -->
    <view v-if="isMock && visible.length" class="coupon-list__mock-tip">示例数据 · 后端暂未连接</view>

    <!-- 3. 券卡片：面额/门槛/有效期/状态（§2.4 不可用灰显并标注原因，不隐藏；§3.3 可用券可点去下单） -->
    <CSkeleton v-if="loading && !loaded" type="card" />
    <CEmpty v-else-if="!visible.length" icon="empty-coupon" text="该分组暂无优惠券" button-text="" />
    <template v-else>
      <view
        v-for="c in visible"
        :key="c.id"
        class="cp-card"
        :class="{ 'cp-card--dim': !usable(c) }"
        @tap="useCoupon(c)"
      >
        <!-- 左侧面额区 -->
        <view class="cp-card__face">
          <text class="cp-card__amount">{{ faceText(c) }}</text>
          <text class="cp-card__scope">{{ SCOPE_TEXT[c.scope] }}券</text>
        </view>
        <!-- 右侧信息区 -->
        <view class="cp-card__main">
          <view class="cp-card__head">
            <text class="cp-card__name">{{ typeText(c) }}</text>
            <text class="cp-card__status" :class="{ 'cp-card__status--ok': usable(c) }">
              {{ statusText(c) }}
            </text>
          </view>
          <text class="cp-card__cond">{{ minSpendText(c) }}</text>
          <text class="cp-card__valid">
            {{ fmtDate(c.valid_from) }} ~ {{ fmtDate(c.valid_to) }}
          </text>
          <text v-if="c.code" class="cp-card__code">券码 {{ c.code }}</text>
          <!-- 4. 行动区：可用券给出下单入口；不可用券标注原因（§2.4），被占用券另给订单入口 -->
          <view class="cp-card__foot">
            <text v-if="usable(c)" class="cp-card__use">去使用 ›</text>
            <template v-else>
              <text class="cp-card__reason">{{ reasonOf(c) }}</text>
              <!-- 只有拿到 order_id 才给订单入口（老数据两字段皆空时跳过去也认不出是哪一单） -->
              <text v-if="c.order_id != null" class="cp-card__use" @tap.stop="goOrders(c.order_id)">
                查看订单 ›
              </text>
            </template>
          </view>
        </view>
      </view>
    </template>
  </view>
</template>

<script setup lang="ts">
/**
 * FE4 · 我的券包 — Phase 3 (M3)
 * 依据：docs/split/03-页面布局与交互说明.md §5.4-4 我的福利（券包分类）
 *       §3.3 券包 → 点击可用券 → 跳转对应商家/标准 SKU 下单页（自动带券）
 *       §2.4 券过期/不可用 → 灰显并标注原因，不隐藏
 * 契约：GET /api/coupon/list（status：1未用 2已用 3过期 4作废；CouponOut 已含 used_at / order_id）
 * 【假设】① 后端尚未部署：请求失败时回退内置示例券并标注；
 *         ② scope=4 通用券仅在「全部」展示（不重复归入吃/动分组）；
 *         ③ 下单即锁券（后端建单时置 status=2 + order_id，used_at 在核销/消费时写），
 *           本页按新字段三态分流：used_at 非空 → 已使用；order_id 非空且 used_at 空 → 已占用
 *           （待核销，取消订单可退回）；两者都空的老数据保守呈现「已占用」，不谎报「已使用」；
 *         ④ status=1 但 valid_to 已过的券，前端兜底按过期灰显（与后端 _display_status 同口径）；
 *         ⑤ 券参数以 coupon_id 透传给下游：merchant/detail.vue、merchant/merchant.vue、
 *           order/confirm.vue 三页都已读取并带到下单链路（confirm 还做可用性复核）。
 */
import { computed, ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { getCoupons } from '@/api/order'
import { useToast } from '@/composables/useToast'
import type { CouponOut } from '@/types/api'

const TABS = [
  { key: 'all', label: '全部' },
  { key: '1', label: '吃的' },
  { key: '2', label: '动的' },
  { key: '3', label: '异业' },
  { key: 'invalid', label: '已失效' },
] as const

type TabKey = (typeof TABS)[number]['key']

const SCOPE_TEXT: Record<number, string> = { 1: '吃', 2: '动', 3: '异业', 4: '通用' }

/* ---------- Mock 兜底数据（结构对齐 CouponOut） ---------- */

const MOCK_AVAILABLE: CouponOut[] = [
  { id: 3051, code: 'CP-3051', type: 1, scope: 1, amount: 3, discount_rate: null, min_spend: 20, merchant_id: null, status: 1, valid_from: '2026-09-01T00:00:00+08:00', valid_to: '2026-10-31T23:59:59+08:00' },
  { id: 3052, code: 'CP-3052', type: 2, scope: 1, amount: 0, discount_rate: 0.85, min_spend: 0, merchant_id: null, status: 1, valid_from: '2026-09-01T00:00:00+08:00', valid_to: '2026-10-31T23:59:59+08:00' },
  { id: 3053, code: 'CP-3053', type: 4, scope: 2, amount: 20, discount_rate: null, min_spend: 0, merchant_id: null, status: 1, valid_from: '2026-09-01T00:00:00+08:00', valid_to: '2026-10-31T23:59:59+08:00' },
  { id: 3054, code: 'CP-3054', type: 1, scope: 3, amount: 5, discount_rate: null, min_spend: 50, merchant_id: null, status: 1, valid_from: '2026-09-01T00:00:00+08:00', valid_to: '2026-10-31T23:59:59+08:00' },
  // 限商家券：验证「可用券 → 指定商家详情」跳转（merchant_id 与商家 mock 同源）
  { id: 3055, code: 'CP-3055', type: 1, scope: 1, amount: 8, discount_rate: null, min_spend: 30, merchant_id: 101, status: 1, valid_from: '2026-09-01T00:00:00+08:00', valid_to: '2026-10-31T23:59:59+08:00' },
]

/**
 * status=2 两种态（契约 CouponOut.used_at / order_id，见【假设】③）：
 * 3061 下单锁定未消费（used_at=null + order_id）→「已占用」；
 * 3065 已核销（used_at 非空）→「已使用」。
 */
const MOCK_OCCUPIED: CouponOut[] = [
  { id: 3061, code: 'CP-3061', type: 1, scope: 1, amount: 5, discount_rate: null, min_spend: 30, merchant_id: null, status: 2, valid_from: '2026-08-01T00:00:00+08:00', valid_to: '2026-08-31T23:59:59+08:00', used_at: null, order_id: 8801 },
  { id: 3065, code: 'CP-3065', type: 4, scope: 2, amount: 15, discount_rate: null, min_spend: 0, merchant_id: null, status: 2, valid_from: '2026-08-01T00:00:00+08:00', valid_to: '2026-08-31T23:59:59+08:00', used_at: '2026-08-20T12:30:00+08:00', order_id: 8800 },
]

/** status=3 过期 + status=4 作废 */
const MOCK_LAPSED: CouponOut[] = [
  { id: 3062, code: 'CP-3062', type: 4, scope: 2, amount: 10, discount_rate: null, min_spend: 0, merchant_id: null, status: 3, valid_from: '2026-08-01T00:00:00+08:00', valid_to: '2026-08-31T23:59:59+08:00' },
  { id: 3063, code: 'CP-3063', type: 1, scope: 3, amount: 15, discount_rate: null, min_spend: 60, merchant_id: null, status: 4, valid_from: '2026-08-01T00:00:00+08:00', valid_to: '2026-12-31T23:59:59+08:00' },
]

/* ---------- 状态 ---------- */

const toast = useToast()

const activeTab = ref<TabKey>('all')
const available = ref<CouponOut[]>([]) // status=1 未用
const occupied = ref<CouponOut[]>([]) // status=2 已被订单占用 / 已核销
const lapsed = ref<CouponOut[]>([]) // status=3 过期 + status=4 作废
const loading = ref(true)
const loaded = ref(false)
const isMock = ref(false)

/** 「已失效」分组：占用与失效一律灰显保留可见，不再与「已过期」混称（§2.4） */
const invalid = computed<CouponOut[]>(() => [...occupied.value, ...lapsed.value])

/** 当前 tab 可见券列表 */
const visible = computed<CouponOut[]>(() => {
  if (activeTab.value === 'all') return available.value
  if (activeTab.value === 'invalid') return invalid.value
  const scope = Number(activeTab.value)
  return available.value.filter((c) => c.scope === scope)
})

/* ---------- 工具 ---------- */

/** status=1 但已过 valid_to：前端兜底按过期处理 */
function expiredOf(c: CouponOut): boolean {
  return !!c.valid_to && new Date(c.valid_to).getTime() < Date.now()
}

/** 可用性判定：不可用券保留可见只灰显（§2.4），不参与跳转下单 */
function usable(c: CouponOut): boolean {
  return c.status === 1 && !expiredOf(c)
}

/** 已核销/已消费（契约 used_at 非空） */
function settled(c: CouponOut): boolean {
  return c.used_at != null
}

/** 被订单占用、尚未消费（可随订单取消退回） */
function locked(c: CouponOut): boolean {
  return c.status === 2 && !settled(c)
}

/** 不可用原因文案（§2.4 灰显并标注原因）；status=2 按 used_at / order_id 三态分流 */
function reasonOf(c: CouponOut): string {
  if (c.status === 2) {
    if (settled(c)) return '已核销使用，不可重复使用'
    return c.order_id != null
      ? '已被订单占用，待核销；取消该订单可退回'
      : '已用于下单或已核销，不可重复使用'
  }
  if (c.status === 4) return '券已作废'
  if (c.status === 3 || expiredOf(c)) return '有效期已结束'
  return ''
}

function faceText(c: CouponOut): string {
  // discount_rate 为 0-1 比例（0.85=8.5 折），与契约/后端一致
  if (c.type === 2) return `${((c.discount_rate ?? 1) * 10).toFixed(1)}折`
  if (c.type === 3) return '免单'
  return `¥${c.amount}`
}

function typeText(c: CouponOut): string {
  return { 1: '满减券', 2: '折扣券', 3: '免费券', 4: '体验券' }[c.type] || '优惠券'
}

function minSpendText(c: CouponOut): string {
  return c.min_spend > 0 ? `满 ${c.min_spend} 元可用` : '无门槛'
}

function statusText(c: CouponOut): string {
  // status=2 的三态：used_at 非空 → 已使用；否则（含老数据两字段皆空）→ 已占用，不谎报已消费
  if (c.status === 2) return settled(c) ? '已使用' : '已占用'
  if (c.status === 4) return '已作废'
  if (c.status === 3 || expiredOf(c)) return '已过期'
  return '可使用'
}

function fmtDate(iso?: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '—' : `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/* ---------- 数据加载 ---------- */

async function loadCoupons() {
  loading.value = true
  try {
    // status=1 是主数据：失败即整体回落示例券；2/3/4 任一失败只让对应分组为空
    const [ava, occ, exp, voided] = await Promise.all([
      getCoupons({ status: 1, page_size: 50 }),
      getCoupons({ status: 2, page_size: 50 }).catch(() => null),
      getCoupons({ status: 3, page_size: 50 }).catch(() => null),
      getCoupons({ status: 4, page_size: 50 }).catch(() => null),
    ])
    available.value = ava?.items ?? []
    occupied.value = occ?.items ?? []
    lapsed.value = [...(exp?.items ?? []), ...(voided?.items ?? [])]
    isMock.value = false
  } catch (e) {
    // request 层已统一 toast；兜底内置示例券
    available.value = MOCK_AVAILABLE
    occupied.value = MOCK_OCCUPIED
    lapsed.value = MOCK_LAPSED
    isMock.value = true
  } finally {
    loading.value = false
    loaded.value = true
  }
}

/* ---------- 跳转（§3.3 券包 → 点击可用券 → 下单入口） ---------- */

/**
 * 点可用券：限商家券 → 该商家详情；不限商家（merchant_id 为 NULL）→ 商家列表自选。
 * 参数名沿用下游既有约定：detail 页 onLoad 读 id（商家 id），
 * coupon_id 沿用契约 OrderCreateIn 字段名，由 detail / merchant / confirm 三页读取并透传（【假设】⑤）。
 */
function useCoupon(c: CouponOut) {
  if (!usable(c)) {
    toast.info({ title: reasonOf(c) })
    return
  }
  if (c.merchant_id != null) {
    uni.navigateTo({ url: `/pages/merchant/detail?id=${c.merchant_id}&coupon_id=${c.id}` })
    return
  }
  uni.navigateTo({ url: `/pages/merchant/merchant?coupon_id=${c.id}` })
}

/**
 * 被占用券 → 我的订单（§3.1 页面 11 入口含「券包」，用于找回核销码）。
 * order_id 随 URL 带过去，便于订单页后续定位/高亮；**当前 order/list.vue 只读自己的分页状态，
 * 尚未消费该参数**（落到订单列表首页），要在列表里精确过滤需改 list.vue，超出本次可改清单。
 */
function goOrders(orderId?: number | null) {
  const query = orderId != null ? `?order_id=${orderId}` : ''
  uni.navigateTo({ url: `/pages/order/list${query}` })
}

function switchTab(key: TabKey) {
  activeTab.value = key
}

/* ---------- 生命周期 ---------- */

onLoad(() => {
  void loadCoupons()
})
</script>

<style lang="scss" scoped>
.coupon-list {
  padding: $space-md;
  padding-bottom: calc(#{$space-xl} + env(safe-area-inset-bottom));

  // 1. scope 分组 tabs
  &__tabs {
    display: flex;
    gap: $space-xs;
    margin-bottom: $space-md;
  }

  &__tab {
    flex: 1;
    padding: $space-sm 0;
    font-size: $t-24;
    color: $text-2;
    text-align: center;
    background: $card;
    border: 1rpx solid $border;
    border-radius: $radius-sm;

    &--active {
      color: $brand-dark;
      background: rgba($brand, 0.1);
      border-color: $brand;
      font-weight: 500;
    }
  }

  // 2. Mock 兜底标注
  &__mock-tip {
    padding: $space-sm $space-md;
    margin-bottom: $space-md;
    font-size: $t-22;
    color: $warn;
    text-align: center;
    background: rgba($warn, 0.1);
    border-radius: $radius-sm;
  }
}

// 3. 券卡片（§4.11：左面额 + 右信息；不可用置灰但仍可见）
.cp-card {
  display: flex;
  gap: $space-md;
  padding: $space-md;
  margin-bottom: $space-md;
  background: $card;
  border-radius: $radius;
  box-shadow: $shadow;

  // 按下反馈（置于普通声明之后，避免 Sass mixed-decls 告警）
  @include press;

  &--dim {
    opacity: 0.5;

    // 灰显卡按下不得回亮（press 的 :active opacity 会盖过 0.5）
    &:active {
      opacity: 0.5;
    }
  }

  &__face {
    @include flex-center(column);

    flex: none;
    width: 170rpx;
    background: rgba($brand, 0.1);
    border-radius: $radius-sm;

    // 不可用：面额区去色
    .cp-card--dim & {
      background: $bg;
    }
  }

  &__amount {
    font-size: $t-num-lg;
    font-weight: 700;
    color: $brand;

    .cp-card--dim & {
      color: $text-3;
    }
  }

  &__scope {
    margin-top: 4rpx;
    font-size: $t-22;
    color: $text-3;
  }

  &__main {
    flex: 1;
    min-width: 0;
  }

  &__head {
    @include flex-between;

    margin-bottom: $space-xs;
  }

  &__name {
    flex: 1;
    min-width: 0;
    font-size: $t-28;
    font-weight: 500;
    color: $text-1;
  }

  &__status {
    flex: none;
    margin-left: $space-sm;
    font-size: $t-22;
    color: $text-3;

    &--ok {
      color: $brand;
    }
  }

  &__cond,
  &__valid {
    display: block;
    font-size: $t-22;
    color: $text-2;
  }

  &__valid {
    margin-top: $space-xs;
    color: $text-3;
  }

  &__code {
    display: block;
    margin-top: $space-xs;
    font-size: $t-22;
    color: $text-3;
  }

  // 4. 行动区：可用「去使用」/ 不可用标注原因（§2.4）
  &__foot {
    display: flex;
    align-items: center;
    margin-top: $space-xs;
  }

  &__use {
    margin-left: auto;
    font-size: $t-22;
    color: $brand;
  }

  &__reason {
    flex: 1;
    min-width: 0;
    font-size: $t-22;
    color: $danger;
  }
}
</style>
