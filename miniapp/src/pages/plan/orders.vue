<template>
  <view class="pos">
    <!-- 状态 tabs：全部 / 待支付(1) / 已支付(2) / 已取消(3) -->
    <view class="pos__tabs">
      <text
        v-for="t in TABS"
        :key="t.label"
        class="pos__tab"
        :class="{ 'pos__tab--active': activeStatus === t.status }"
        @tap="switchTab(t.status)"
      >
        {{ t.label }}
      </text>
    </view>

    <CSkeleton v-if="loading && !list.length" type="card" />
    <CError v-else-if="error && !list.length" @retry="() => loadPage(true)" />
    <CEmpty
      v-else-if="!list.length"
      icon="empty-order"
      text="暂无订阅订单"
      button-text="去开通"
      @action="goPlan"
    />
    <template v-else>
      <view v-for="o in list" :key="o.id" class="p-card">
        <view class="p-card__head">
          <text class="p-card__tier">{{ TIER_TEXT[o.tier] || `档位 ${o.tier}` }}</text>
          <text class="p-card__status" :class="`p-card__status--${o.status}`">
            {{ STATUS_TEXT[o.status] || '未知' }}
          </text>
        </view>
        <view class="p-card__body">
          <text class="p-card__no">{{ o.order_no }}</text>
          <text class="p-card__amount">¥{{ o.pay_amount.toFixed(2) }}</text>
        </view>
        <view class="p-card__foot">
          <text class="p-card__time">{{ fmtTime(o.created_at) }}</text>
          <!-- 待支付：继续支付（重走 payPlanOrder，订单 15 分钟后过期 → 5003） -->
          <CButton
            v-if="o.status === 1"
            size="sm"
            :loading="payingId === o.id"
            @click.stop="repay(o)"
          >
            继续支付
          </CButton>
        </view>
      </view>

      <view v-if="loading" class="pos__more">加载中...</view>
      <view v-else-if="!hasMore" class="pos__more">没有更多了</view>
    </template>
  </view>
</template>

<script setup lang="ts">
/**
 * FE · 我的订阅订单 — G2
 * 契约：GET /api/plan/orders（status/page/page_size）、POST /api/plan/order/{id}/pay
 */
import { ref } from 'vue'
import { onLoad, onReachBottom } from '@dcloudio/uni-app'
import { useToast } from '@/composables/useToast'
import { track } from '@/utils/track'
import { getPlanOrders, payPlanOrder } from '@/api/plan'
import type { PlanOrderItem } from '@/types/api'

const TABS: { status: 1 | 2 | 3 | undefined; label: string }[] = [
  { status: undefined, label: '全部' },
  { status: 1, label: '待支付' },
  { status: 2, label: '已支付' },
  { status: 3, label: '已取消' },
]

/** 档位文案（PlanTier：1进阶 2高级 3终身） */
const TIER_TEXT: Record<number, string> = { 1: '进阶版', 2: '高级版', 3: '终身版' }
/** 订单状态文案（PlanOrderStatus） */
const STATUS_TEXT: Record<number, string> = { 1: '待支付', 2: '已支付', 3: '已取消' }

const PAGE_SIZE = 10

const toast = useToast()

const activeStatus = ref<1 | 2 | 3 | undefined>(undefined)
const list = ref<PlanOrderItem[]>([])
const page = ref(1)
const hasMore = ref(false)
const loading = ref(false)
const error = ref(false)
/** 「继续支付」进行中的订单 id */
const payingId = ref(-1)

function fmtTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

async function loadPage(reset: boolean) {
  if (loading.value) return
  loading.value = true
  if (reset) {
    page.value = 1
    error.value = false
  }
  try {
    const data = await getPlanOrders({
      status: activeStatus.value,
      page: page.value,
      page_size: PAGE_SIZE,
    })
    const items = data?.items ?? []
    list.value = reset ? items : [...list.value, ...items]
    hasMore.value = list.value.length < (data?.page?.total ?? 0)
  } catch (e) {
    if (reset) {
      list.value = []
      error.value = true
    }
    hasMore.value = false
    void e
  } finally {
    loading.value = false
  }
}

function switchTab(status: 1 | 2 | 3 | undefined) {
  if (status === activeStatus.value) return
  activeStatus.value = status
  void loadPage(true)
}

/** 继续支付：mock/H5 下拿到订单即视为支付成功，随后刷新列表 */
async function repay(o: PlanOrderItem) {
  if (payingId.value !== -1) return
  payingId.value = o.id
  try {
    const payData = await payPlanOrder(o.id)
    // 会员付费转化（G2 埋点）
    track('plan_pay', { order_id: o.id, tier: o.tier, amount: o.pay_amount })
    void payData
    toast.success({ title: '支付成功(模拟)' })
    await loadPage(true)
  } catch (e) {
    // request 层已统一 toast（含 5003 订单超时）
    void e
  } finally {
    payingId.value = -1
  }
}

function goPlan() {
  uni.navigateTo({ url: '/pages/plan/index' })
}

onLoad(() => {
  void loadPage(true)
})

onReachBottom(() => {
  if (!hasMore.value || loading.value) return
  page.value += 1
  void loadPage(false)
})
</script>

<style lang="scss" scoped>
.pos {
  padding: $space-md;
  padding-bottom: calc(#{$space-xl} + env(safe-area-inset-bottom));

  &__tabs {
    display: flex;
    gap: $space-sm;
    margin-bottom: $space-md;
  }

  &__tab {
    flex: 1;
    padding: $space-sm 0;
    font-size: $t-26;
    color: $text-2;
    text-align: center;
    background: $card;
    border: 1rpx solid $border;
    border-radius: $radius-sm;

    &--active {
      color: $brand-dark;
      background: rgba(34, 197, 94, 0.1);
      border-color: $brand;
      font-weight: 500;
    }
  }

  &__more {
    padding: $space-md 0;
    font-size: $t-22;
    color: $text-3;
    text-align: center;
  }
}

.p-card {
  padding: $space-lg;
  margin-bottom: $space-md;
  background: $card;
  border-radius: $radius;
  box-shadow: $shadow;

  &__head {
    @include flex-between;

    margin-bottom: $space-sm;
  }

  &__tier {
    flex: 1;
    min-width: 0;
    font-size: $t-28;
    font-weight: 500;
    color: $text-1;
  }

  &__status {
    flex: none;
    margin-left: $space-sm;
    font-size: $t-24;

    &--1 {
      color: $warn;
    }

    &--2 {
      color: $brand;
    }

    &--3 {
      color: $text-3;
    }
  }

  &__body {
    @include flex-between;

    margin-bottom: $space-sm;
  }

  &__no {
    flex: 1;
    min-width: 0;
    font-size: $t-22;
    color: $text-3;
  }

  &__amount {
    flex: none;
    margin-left: $space-sm;
    font-size: $t-num-md;
    font-weight: 700;
    color: $text-1;
  }

  &__foot {
    @include flex-between;

    gap: $space-sm;
  }

  &__time {
    flex: 1;
    font-size: $t-22;
    color: $text-3;
  }
}
</style>
