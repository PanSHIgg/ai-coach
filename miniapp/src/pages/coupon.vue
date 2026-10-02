<template>
  <view class="coupon-list">
    <!-- 1. scope 分组 tabs：全部 / 吃 / 动 / 异业 / 已过期 -->
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

    <!-- 3. 券卡片：面额/门槛/有效期/状态（已用/过期置灰） -->
    <CSkeleton v-if="loading && !loaded" type="card" />
    <CEmpty v-else-if="!visible.length" icon="empty-coupon" text="该分组暂无优惠券" button-text="" />
    <template v-else>
      <view
        v-for="c in visible"
        :key="c.id"
        class="cp-card"
        :class="{ 'cp-card--dim': c.status !== 1 || expiredOf(c) }"
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
            <text
              class="cp-card__status"
              :class="{ 'cp-card__status--ok': c.status === 1 && !expiredOf(c) }"
            >
              {{ statusText(c) }}
            </text>
          </view>
          <text class="cp-card__cond">{{ minSpendText(c) }}</text>
          <text class="cp-card__valid">
            {{ fmtDate(c.valid_from) }} ~ {{ fmtDate(c.valid_to) }}
          </text>
          <text v-if="c.code" class="cp-card__code">券码 {{ c.code }}</text>
        </view>
      </view>
    </template>
  </view>
</template>

<script setup lang="ts">
/**
 * FE4 · 我的券包 — Phase 3 (M3)
 * 依据：docs/split/03-页面布局与交互说明.md §5.4-4 我的福利（券包分类）
 * 契约：GET /api/coupon/list（status：1未用 2已用 3过期 4作废）
 * 【假设】① 后端尚未部署：请求失败时回退内置示例券并标注；
 *         ② scope=4 通用券仅在「全部」展示（不重复归入吃/动分组）；
 *         ③ 已用券（status=2）并入「已过期」标签页灰显展示；
 *         ④ status=1 但 valid_to 已过的券，前端兜底按过期灰显。
 */
import { computed, ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { getCoupons } from '@/api/order'
import type { CouponOut } from '@/types/api'

const TABS = [
  { key: 'all', label: '全部' },
  { key: '1', label: '吃的' },
  { key: '2', label: '动的' },
  { key: '3', label: '异业' },
  { key: 'expired', label: '已过期' },
] as const

type TabKey = (typeof TABS)[number]['key']

const SCOPE_TEXT: Record<number, string> = { 1: '吃', 2: '动', 3: '异业', 4: '通用' }

/* ---------- Mock 兜底数据（结构对齐 CouponOut） ---------- */

const MOCK_AVAILABLE: CouponOut[] = [
  { id: 3051, code: 'CP-3051', type: 1, scope: 1, amount: 3, discount_rate: null, min_spend: 20, merchant_id: null, status: 1, valid_from: '2026-09-01T00:00:00+08:00', valid_to: '2026-10-31T23:59:59+08:00' },
  { id: 3052, code: 'CP-3052', type: 2, scope: 1, amount: 0, discount_rate: 0.85, min_spend: 0, merchant_id: null, status: 1, valid_from: '2026-09-01T00:00:00+08:00', valid_to: '2026-10-31T23:59:59+08:00' },
  { id: 3053, code: 'CP-3053', type: 4, scope: 2, amount: 20, discount_rate: null, min_spend: 0, merchant_id: null, status: 1, valid_from: '2026-09-01T00:00:00+08:00', valid_to: '2026-10-31T23:59:59+08:00' },
  { id: 3054, code: 'CP-3054', type: 1, scope: 3, amount: 5, discount_rate: null, min_spend: 50, merchant_id: null, status: 1, valid_from: '2026-09-01T00:00:00+08:00', valid_to: '2026-10-31T23:59:59+08:00' },
]

const MOCK_INVALID: CouponOut[] = [
  { id: 3061, code: 'CP-3061', type: 1, scope: 1, amount: 5, discount_rate: null, min_spend: 30, merchant_id: null, status: 2, valid_from: '2026-08-01T00:00:00+08:00', valid_to: '2026-08-31T23:59:59+08:00' },
  { id: 3062, code: 'CP-3062', type: 4, scope: 2, amount: 10, discount_rate: null, min_spend: 0, merchant_id: null, status: 3, valid_from: '2026-08-01T00:00:00+08:00', valid_to: '2026-08-31T23:59:59+08:00' },
]

/* ---------- 状态 ---------- */

const activeTab = ref<TabKey>('all')
const available = ref<CouponOut[]>([]) // status=1 未用
const invalid = ref<CouponOut[]>([]) // status=2 已用 + status=3 过期
const loading = ref(true)
const loaded = ref(false)
const isMock = ref(false)

/** 当前 tab 可见券列表 */
const visible = computed<CouponOut[]>(() => {
  if (activeTab.value === 'all') return available.value
  if (activeTab.value === 'expired') return invalid.value
  const scope = Number(activeTab.value)
  return available.value.filter((c) => c.scope === scope)
})

/* ---------- 工具 ---------- */

/** status=1 但已过 valid_to：前端兜底按过期处理 */
function expiredOf(c: CouponOut): boolean {
  return !!c.valid_to && new Date(c.valid_to).getTime() < Date.now()
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
  if (c.status === 2) return '已使用'
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
    const [ava, inv] = await Promise.all([
      getCoupons({ status: 1, page_size: 50 }),
      getCoupons({ status: 2, page_size: 50 }).catch(() => null),
    ])
    const expired = await getCoupons({ status: 3, page_size: 50 })
    available.value = ava?.items ?? []
    invalid.value = [...(inv?.items ?? []), ...(expired?.items ?? [])]
    isMock.value = false
  } catch (e) {
    // request 层已统一 toast；兜底内置示例券
    available.value = MOCK_AVAILABLE
    invalid.value = MOCK_INVALID
    isMock.value = true
  } finally {
    loading.value = false
    loaded.value = true
  }
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

// 3. 券卡片（§4.11：左面额 + 右信息；已用/过期置灰）
.cp-card {
  display: flex;
  gap: $space-md;
  padding: $space-md;
  margin-bottom: $space-md;
  background: $card;
  border-radius: $radius;
  box-shadow: $shadow;

  &--dim {
    opacity: 0.5;
  }

  &__face {
    @include flex-center(column);

    flex: none;
    width: 170rpx;
    background: rgba($brand, 0.1);
    border-radius: $radius-sm;

    // 已用/过期：面额区去色
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
}
</style>
