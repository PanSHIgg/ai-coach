<template>
  <view class="confirm">
    <!-- 1. 订单明细卡 -->
    <view class="card">
      <view class="card__title">订单明细</view>
      <view v-for="it in items" :key="it.sku_id" class="line">
        <view class="line__main">
          <text class="line__name">{{ it.name }}</text>
          <text class="line__sub">¥{{ it.price.toFixed(2) }} × {{ it.qty }}</text>
        </view>
        <text class="line__sum">¥{{ (it.price * it.qty).toFixed(2) }}</text>
      </view>
      <view class="card__foot">
        <text>共 {{ totalQty }} 件</text>
        <text class="card__total">¥{{ totalAmount.toFixed(2) }}</text>
      </view>
    </view>

    <!-- 2. 选券区（status=1 未用券；可用可选 / 不可用灰显 + 原因） -->
    <view class="card">
      <view class="card__title">选择优惠券</view>
      <view v-if="isMock" class="card__mock">示例数据 · 后端暂未连接</view>

      <CSkeleton v-if="couponLoading" :rows="3" />
      <CEmpty v-else-if="!coupons.length" icon="empty-coupon" text="暂无可用券" button-text="" />
      <template v-else>
        <view
          v-for="c in coupons"
          :key="c.id"
          class="coupon"
          :class="{ 'coupon--off': !!reasonOf(c) }"
          @tap="toggleCoupon(c)"
        >
          <view class="coupon__face">
            <text class="coupon__amount">{{ faceText(c) }}</text>
            <text class="coupon__cond">满 {{ c.min_spend }} 可用</text>
          </view>
          <view class="coupon__main">
            <text class="coupon__name">{{ SCOPE_TEXT[c.scope] }}券 · {{ typeText(c) }}</text>
            <text class="coupon__valid">{{ fmtDate(c.valid_from) }} ~ {{ fmtDate(c.valid_to) }}</text>
            <text v-if="reasonOf(c)" class="coupon__reason">{{ reasonOf(c) }}</text>
          </view>
          <view class="coupon__pick" :class="{ 'coupon__pick--on': couponId === c.id && !reasonOf(c) }">
            {{ couponId === c.id && !reasonOf(c) ? '✓' : '' }}
          </view>
        </view>
      </template>
    </view>

    <!-- 3. 合计卡（优惠为前端预估，最终以服务端重算为准） -->
    <view class="card">
      <view class="sum">
        <view class="sum__row">
          <text>商品总额</text>
          <text>¥{{ totalAmount.toFixed(2) }}</text>
        </view>
        <view class="sum__row">
          <text>优惠券</text>
          <text :class="{ 'sum__minus': discount > 0 }">
            {{ discount > 0 ? `-¥${discount.toFixed(2)}` : '-¥0.00' }}
          </text>
        </view>
        <view class="sum__row sum__row--total">
          <text>待支付</text>
          <text class="sum__pay">¥{{ payAmount.toFixed(2) }}</text>
        </view>
        <text class="sum__tip">金额以服务端重算为准</text>
      </view>
    </view>

    <!-- 4. 提交栏 -->
    <view class="confirm__bar">
      <view class="confirm__bar-main">
        <text class="confirm__bar-label">合计</text>
        <text class="confirm__bar-amount">¥{{ payAmount.toFixed(2) }}</text>
      </view>
      <CButton size="md" :loading="submitting" :disabled="!items.length" @click="submit">
        提交并支付
      </CButton>
    </view>
  </view>
</template>

<script setup lang="ts">
/**
 * FE4 · 订单确认 — Phase 3 (M3)
 * 依据：docs/split/03-页面布局与交互说明.md §5.2-7 商家卡 [预约] → 确认订单
 * 契约：POST /api/order（OrderCreatedData）→ POST /api/order/{id}/pay（PayData）
 *       GET /api/coupon/list?status=1（CouponPageData）
 * 【假设】① 后端尚未部署：券请求失败时回退内置示例券并标注；
 *         ② pay_params 在 H5/开发态无法真正拉起微信支付，直接视为支付成功（模拟）；
 *         ③ discount_rate 为 0-1 比例（0.85=8.5 折），与契约/后端一致；
 *         ④ scope=3 异业券不做商家类目限制；可用性前端按 min_spend/scope/valid_to 预判，
 *           最终以后端重算为准。
 */
import { computed, ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { createOrder, payOrder, getCoupons } from '@/api/order'
import { useToast } from '@/composables/useToast'
import { track } from '@/utils/track'
import type { CouponOut } from '@/types/api'

const SCOPE_TEXT: Record<number, string> = { 1: '吃', 2: '动', 3: '异业', 4: '通用' }

/** detail 页带来的购物项（sku_id + 展示字段；提交仅传 sku_id/qty） */
interface CartItem {
  sku_id: number
  name: string
  price: number
  qty: number
}

/* ---------- Mock 兜底数据（结构对齐 CouponOut） ---------- */

const MOCK_COUPONS: CouponOut[] = [
  { id: 3051, code: 'CP-3051', type: 1, scope: 1, amount: 3, discount_rate: null, min_spend: 20, merchant_id: null, status: 1, valid_from: '2026-09-01T00:00:00+08:00', valid_to: '2026-10-31T23:59:59+08:00' },
  { id: 3052, code: 'CP-3052', type: 2, scope: 1, amount: 0, discount_rate: 0.85, min_spend: 0, merchant_id: null, status: 1, valid_from: '2026-09-01T00:00:00+08:00', valid_to: '2026-10-31T23:59:59+08:00' },
  { id: 3053, code: 'CP-3053', type: 4, scope: 2, amount: 20, discount_rate: null, min_spend: 0, merchant_id: null, status: 1, valid_from: '2026-09-01T00:00:00+08:00', valid_to: '2026-10-31T23:59:59+08:00' },
  { id: 3054, code: 'CP-3054', type: 1, scope: 3, amount: 5, discount_rate: null, min_spend: 50, merchant_id: null, status: 1, valid_from: '2026-09-01T00:00:00+08:00', valid_to: '2026-10-31T23:59:59+08:00' },
]

/* ---------- 状态 ---------- */

const toast = useToast()

const merchantId = ref(0)
const merchantCategory = ref('')
const items = ref<CartItem[]>([])
const coupons = ref<CouponOut[]>([])
const couponLoading = ref(true)
const isMock = ref(false)
const couponId = ref<number | null>(null)
const submitting = ref(false)

const totalQty = computed(() => items.value.reduce((sum, it) => sum + it.qty, 0))
const totalAmount = computed(() =>
  items.value.reduce((sum, it) => sum + it.price * it.qty, 0),
)

/** 前端预估优惠（最终以服务端重算为准） */
const discount = computed(() => {
  const c = coupons.value.find((x) => x.id === couponId.value)
  if (!c || reasonOf(c)) return 0
  let val = 0
  if (c.type === 1) {
    val = c.amount // 满减
  } else if (c.type === 2) {
    const rate = c.discount_rate ?? 1 // 0-1 比例（0.85=8.5 折），与契约/后端一致
    val = totalAmount.value * (1 - rate)
  } else if (c.type === 3) {
    val = totalAmount.value // 免费券 = 免单
  } else {
    val = c.amount // 体验券抵扣
  }
  return Math.min(Math.round(val * 100) / 100, totalAmount.value)
})

const payAmount = computed(() =>
  Math.max(0, Math.round((totalAmount.value - discount.value) * 100) / 100),
)

/* ---------- 券可用性预判（简单版，最终以后端为准） ---------- */

function reasonOf(c: CouponOut): string {
  if (c.valid_to && new Date(c.valid_to).getTime() < Date.now()) return '已过期'
  if (c.min_spend > totalAmount.value) return `满 ${c.min_spend} 元可用，门槛不足`
  if (c.merchant_id != null && c.merchant_id !== merchantId.value) return '仅限指定商家使用'
  if (!scopeMatch(c.scope, merchantCategory.value)) return '适用范围不符'
  return ''
}

/** scope 1吃 / 2动 / 3异业 / 4通用；异业与通用不做类目限制 */
function scopeMatch(scope: number, category: string): boolean {
  if (scope === 3 || scope === 4) return true
  const isFood = /轻食|餐|食|饮/.test(category)
  const isSport = /健身|运动|球|泳/.test(category)
  if (scope === 1) return isFood
  if (scope === 2) return isSport
  return true
}

/* ---------- 券展示 ---------- */

function faceText(c: CouponOut): string {
  if (c.type === 2) return `${((c.discount_rate ?? 1) * 10).toFixed(1)}折`
  if (c.type === 3) return '免单'
  return `¥${c.amount}`
}

function typeText(c: CouponOut): string {
  return { 1: '满减', 2: '折扣', 3: '免费', 4: '体验' }[c.type] || '优惠券'
}

function fmtDate(iso?: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '—' : `${d.getMonth() + 1}-${d.getDate()}`
}

/** 点选/再点取消；不可用券不可选 */
function toggleCoupon(c: CouponOut) {
  if (reasonOf(c)) {
    toast.info({ title: reasonOf(c) })
    return
  }
  couponId.value = couponId.value === c.id ? null : c.id
}

/* ---------- 数据加载 ---------- */

async function loadCoupons() {
  couponLoading.value = true
  try {
    const data = await getCoupons({ status: 1, page_size: 50 })
    coupons.value = data?.items ?? []
    isMock.value = false
  } catch (e) {
    // request 层已统一 toast；兜底内置示例券
    coupons.value = MOCK_COUPONS
    isMock.value = true
  } finally {
    couponLoading.value = false
  }
}

/* ---------- 提交：createOrder → payOrder → 模拟支付成功 ---------- */

async function submit() {
  if (submitting.value || !items.value.length) return
  submitting.value = true
  try {
    const created = await createOrder({
      merchant_id: merchantId.value,
      items: items.value.map((it) => ({ sku_id: it.sku_id, qty: it.qty })),
      coupon_id: couponId.value,
    })
    // H5/开发态无法拉起微信支付：拿到 pay_params 后直接视为支付成功（模拟）
    await payOrder(created.order_id)
    // 扫码转化率（分子）：订单支付成功
    track('order_pay', {
      order_id: created.order_id,
      merchant_id: merchantId.value,
      amount: payAmount.value,
    })
    toast.success({ title: '支付成功(模拟)' })
    setTimeout(() => {
      uni.redirectTo({ url: '/pages/order/list' })
    }, 1200)
  } catch (e) {
    // request 层已统一 toast（含 5001 商家停业 / 5002 券不可用）
    submitting.value = false
  }
}

/* ---------- 生命周期 ---------- */

onLoad((options) => {
  const opt = (options as
    | { merchant_id?: string; merchant_name?: string; category?: string; items?: string }
    | undefined) || {}
  merchantId.value = Number(opt.merchant_id) || 0
  merchantCategory.value = opt.category ? decodeURIComponent(opt.category) : ''
  try {
    const parsed = JSON.parse(decodeURIComponent(opt.items || '[]')) as CartItem[]
    items.value = Array.isArray(parsed)
      ? parsed.filter(
          (it) =>
            typeof it?.sku_id === 'number' &&
            typeof it?.qty === 'number' &&
            typeof it?.price === 'number' &&
            it.qty > 0,
        )
      : []
  } catch {
    items.value = []
  }
  void loadCoupons()
})
</script>

<style lang="scss" scoped>
.confirm {
  padding: $space-md;
  padding-bottom: calc(180rpx + env(safe-area-inset-bottom));
}

.card {
  padding: $space-lg;
  margin-bottom: $space-md;
  background: $card;
  border-radius: $radius;
  box-shadow: $shadow;

  &__title {
    margin-bottom: $space-md;
    font-size: $t-28;
    font-weight: 500;
    color: $text-1;
  }

  &__mock {
    padding: $space-xs $space-sm;
    margin-bottom: $space-sm;
    font-size: $t-22;
    color: $warn;
    text-align: center;
    background: rgba(245, 158, 11, 0.1);
    border-radius: $radius-sm;
  }

  &__foot {
    @include flex-between;

    padding-top: $space-sm;
    font-size: $t-24;
    color: $text-2;
  }

  &__total {
    font-size: $t-26;
    font-weight: 700;
    color: $text-1;
  }
}

// 明细行
.line {
  @include flex-between;

  gap: $space-sm;
  padding: $space-sm 0;

  &:not(:last-of-type) {
    @include hairline(bottom);
  }

  &__main {
    flex: 1;
    min-width: 0;
  }

  &__name {
    display: block;
    margin-bottom: $space-xs;
    font-size: $t-26;
    color: $text-1;
  }

  &__sub {
    font-size: $t-22;
    color: $text-3;
  }

  &__sum {
    flex: none;
    font-size: $t-26;
    font-weight: 500;
    color: $text-1;
  }
}

// 券卡片
.coupon {
  @include flex-between;

  gap: $space-md;
  padding: $space-md;
  margin-bottom: $space-sm;
  background: $bg;
  border: 1rpx solid $border;
  border-radius: $radius;

  &--off {
    opacity: 0.5;
  }

  &__face {
    @include flex-center(column);

    flex: none;
    width: 150rpx;
    padding: $space-sm 0;
    background: rgba(34, 197, 94, 0.1);
    border-radius: $radius-sm;
  }

  &__amount {
    font-size: $t-num-md;
    font-weight: 700;
    color: $brand;
  }

  &__cond {
    margin-top: 4rpx;
    font-size: $t-22;
    color: $text-3;
  }

  &__main {
    flex: 1;
    min-width: 0;
  }

  &__name {
    display: block;
    margin-bottom: $space-xs;
    font-size: $t-26;
    font-weight: 500;
    color: $text-1;
  }

  &__valid {
    display: block;
    font-size: $t-22;
    color: $text-3;
  }

  &__reason {
    display: block;
    margin-top: $space-xs;
    font-size: $t-22;
    color: $danger;
  }

  &__pick {
    @include flex-center;

    flex: none;
    width: 44rpx;
    height: 44rpx;
    font-size: $t-24;
    color: var(--card);
    background: $border;
    border-radius: 50%;

    &--on {
      background: $brand;
    }
  }
}

// 合计区
.sum {
  &__row {
    @include flex-between;

    padding: $space-xs 0;
    font-size: $t-26;
    color: $text-2;

    &--total {
      padding-top: $space-sm;
      border-top: 1rpx solid $border;
      color: $text-1;
      font-weight: 500;
    }
  }

  &__minus {
    color: $danger;
  }

  &__pay {
    font-size: $t-num-md;
    font-weight: 700;
    color: $brand;
  }

  &__tip {
    display: block;
    margin-top: $space-xs;
    font-size: $t-22;
    color: $text-3;
  }
}

// 提交栏
.confirm__bar {
  @include flex-between;

  position: fixed;
  right: 0;
  bottom: 0;
  left: 0;
  gap: $space-md;
  padding: $space-md $space-lg;
  padding-bottom: calc(#{$space-md} + env(safe-area-inset-bottom));
  background: $card;
  box-shadow: 0 -4rpx 16rpx rgba(0, 0, 0, 0.06);

  &-main {
    flex: 1;
    min-width: 0;
  }

  &-label {
    margin-right: $space-xs;
    font-size: $t-24;
    color: $text-2;
  }

  &-amount {
    font-size: $t-num-lg;
    font-weight: 700;
    color: $brand;
  }
}
</style>
