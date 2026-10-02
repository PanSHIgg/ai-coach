<template>
  <view class="olist">
    <!-- 1. 状态 tabs：待支付(1) / 待核销(2) / 已完成(3) -->
    <view class="olist__tabs">
      <text
        v-for="t in TABS"
        :key="t.status"
        class="olist__tab"
        :class="{ 'olist__tab--active': activeStatus === t.status }"
        @tap="switchTab(t.status)"
      >
        {{ t.label }}
      </text>
    </view>

    <!-- 2. Mock 兜底标注 -->
    <view v-if="isMock && list.length" class="olist__mock-tip">示例数据 · 后端暂未连接</view>

    <!-- 3. 订单卡片：商家名/金额/状态/时间 -->
    <CSkeleton v-if="loading && !list.length" type="card" />
    <CEmpty v-else-if="!list.length" icon="empty-order" text="暂无相关订单" button-text="" />
    <template v-else>
      <view
        v-for="o in list"
        :key="o.id"
        class="o-card"
        @tap="toggleRedeem(o)"
      >
        <view class="o-card__head">
          <text class="o-card__merchant">{{ o.merchant_name || `商家 #${o.merchant_id}` }}</text>
          <text class="o-card__status" :class="`o-card__status--${o.status}`">
            {{ STATUS_TEXT[o.status] || '未知' }}
          </text>
        </view>
        <view class="o-card__body">
          <text class="o-card__no">{{ o.order_no }}</text>
          <text class="o-card__amount">¥{{ o.pay_amount.toFixed(2) }}</text>
        </view>
        <view class="o-card__foot">
          <text class="o-card__time">{{ fmtTime(o.created_at) }}</text>
          <view class="o-card__ops">
            <!-- 已完成：实付金额 -->
            <text v-if="o.status !== 1 && o.discount_amount > 0" class="o-card__save">
              已优惠 ¥{{ o.discount_amount.toFixed(2) }}
            </text>
            <!-- 待支付：继续支付（重走 payOrder） -->
            <CButton
              v-if="o.status === 1"
              size="sm"
              :loading="payingId === o.id"
              @click.stop="repay(o)"
            >
              继续支付
            </CButton>
            <!-- 待核销：申请退款（2 已支付待核销 → 5 已退款，§12.1 退款入口） -->
            <CButton
              v-else-if="o.status === 2"
              size="sm"
              type="ghost"
              :loading="refundingId === o.id"
              @click.stop="refund(o)"
            >
              申请退款
            </CButton>
          </view>
        </view>

        <!-- 待核销：点击展开核销码大字号 -->
        <view v-if="expandedId === o.id && o.redeem_code" class="o-card__redeem">
          <text class="o-card__redeem-label">到店出示核销码</text>
          <text class="o-card__redeem-code">{{ o.redeem_code }}</text>
        </view>
      </view>

      <view v-if="loading" class="olist__more">加载中...</view>
      <view v-else-if="!hasMore" class="olist__more">没有更多了</view>
    </template>
  </view>
</template>

<script setup lang="ts">
/**
 * FE4 · 我的订单 — Phase 3 (M3)
 * 依据：docs/split/03-页面布局与交互说明.md 订单流转：下单→支付→核销码→商家扫码→完成
 * 契约：GET /api/order/list（status 可选）、POST /api/order/{id}/pay
 * 【假设】① 后端尚未部署：请求失败时回退内置示例订单并标注；
 *         ② H5/开发态「继续支付」拿到 pay_params 后直接视为支付成功（模拟），
 *           随后刷新列表；核销由商家侧扫码完成，用户侧仅展示核销码。
 */
import { ref } from 'vue'
import { onLoad, onReachBottom } from '@dcloudio/uni-app'
import { getOrders, payOrder, refundOrder } from '@/api/order'
import { useToast } from '@/composables/useToast'
import { track } from '@/utils/track'
import type { OrderBrief } from '@/types/api'

const TABS = [
  { status: 1 as const, label: '待支付' },
  { status: 2 as const, label: '待核销' },
  { status: 3 as const, label: '已完成' },
] as const

const STATUS_TEXT: Record<number, string> = {
  1: '待支付',
  2: '待核销',
  3: '已完成',
  4: '已取消',
  5: '已退款',
}

const PAGE_SIZE = 10

/* ---------- Mock 兜底数据（结构对齐 OrderBrief） ---------- */

const MOCK_ORDERS: OrderBrief[] = [
  { id: 66001, order_no: 'DD20260928001', merchant_id: 101, merchant_name: '轻食盒子（科技园店）', total_amount: 53, discount_amount: 3, pay_amount: 50, status: 2, redeem_code: 'RD-7XK2QM', expire_at: null, created_at: '2026-09-28T12:30:00+08:00' },
  { id: 66002, order_no: 'DD20260928002', merchant_id: 103, merchant_name: '超级猩猩健身（南山店）', total_amount: 99, discount_amount: 0, pay_amount: 99, status: 2, redeem_code: 'RD-PL4W9D', expire_at: null, created_at: '2026-09-28T10:05:00+08:00' },
  { id: 66003, order_no: 'DD20260927003', merchant_id: 102, merchant_name: '能量沙拉 LAB', total_amount: 30, discount_amount: 0, pay_amount: 30, status: 1, redeem_code: null, expire_at: '2026-09-28T15:30:00+08:00', created_at: '2026-09-27T15:00:00+08:00' },
  { id: 66004, order_no: 'DD20260926004', merchant_id: 104, merchant_name: '乐刻运动 SPACE', total_amount: 50, discount_amount: 5, pay_amount: 45, status: 3, redeem_code: null, expire_at: null, created_at: '2026-09-26T19:20:00+08:00' },
]

/* ---------- 状态 ---------- */

const toast = useToast()

const activeStatus = ref<1 | 2 | 3>(1)
const list = ref<OrderBrief[]>([])
const page = ref(1)
const hasMore = ref(false)
const loading = ref(false)
const isMock = ref(false)
/** 展开核销码的订单 id（待核销单点击展开） */
const expandedId = ref<number | null>(null)
/** 「继续支付」进行中的订单 id */
const payingId = ref(-1)
/** 「申请退款」进行中的订单 id */
const refundingId = ref(-1)

/* ---------- 工具 ---------- */

function fmtTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

/* ---------- 数据加载 ---------- */

async function loadPage(reset: boolean) {
  if (loading.value) return
  loading.value = true
  if (reset) page.value = 1
  try {
    const data = await getOrders({ status: activeStatus.value, page: page.value, page_size: PAGE_SIZE })
    const items = data?.items ?? []
    list.value = reset ? items : [...list.value, ...items]
    const total = data?.page?.total ?? 0
    hasMore.value = list.value.length < total
    isMock.value = false
  } catch (e) {
    // request 层已统一 toast；兜底内置示例订单（按当前 tab 的 status 前端筛）
    if (reset) {
      list.value = MOCK_ORDERS.filter((o) => o.status === activeStatus.value)
    }
    hasMore.value = false
    isMock.value = true
  } finally {
    loading.value = false
  }
}

function switchTab(status: 1 | 2 | 3) {
  if (status === activeStatus.value) return
  activeStatus.value = status
  expandedId.value = null
  void loadPage(true)
}

/* ---------- 交互 ---------- */

/** 待核销订单点击展开/收起核销码 */
function toggleRedeem(o: OrderBrief) {
  if (o.status !== 2 || !o.redeem_code) return
  expandedId.value = expandedId.value === o.id ? null : o.id
}

/** 继续支付：payOrder → H5/开发态直接视为支付成功（模拟）→ 刷新 */
async function repay(o: OrderBrief) {
  if (payingId.value !== -1) return
  payingId.value = o.id
  try {
    await payOrder(o.id)
    // 扫码转化率（分子）：继续支付成功
    track('order_pay', {
      order_id: o.id,
      merchant_id: o.merchant_id,
      amount: o.pay_amount,
    })
    toast.success({ title: '支付成功(模拟)' })
    expandedId.value = null
    await loadPage(true)
  } catch (e) {
    // request 层已统一 toast（含 5003 订单超时）
  } finally {
    payingId.value = -1
  }
}

/**
 * 申请退款：二次确认 → refundOrder → 刷新（§12.1 订单交易退款入口）。
 * 仅「2 已支付待核销」可退（后端 order_service.refund_order：2→5，1/3/4 返回 2001）；
 * 【假设】§2.4「已核销」退款走客服工单，非本接口，故不在已完成单展示此入口。
 */
function refund(o: OrderBrief) {
  if (refundingId.value !== -1) return
  uni.showModal({
    title: '申请退款',
    content: `确认对订单 ${o.order_no} 申请退款吗？退款后该券将作废。`,
    confirmText: '确认退款',
    confirmColor: '#ef4444',
    success: async (res) => {
      if (!res.confirm) return
      refundingId.value = o.id
      try {
        await refundOrder(o.id)
        toast.success({ title: '退款申请成功' })
        expandedId.value = null
        await loadPage(true)
      } catch (e) {
        // request 层已统一 toast（含 2001 订单状态不可退款）
      } finally {
        refundingId.value = -1
      }
    },
  })
}

/* ---------- 生命周期 ---------- */

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
.olist {
  padding: $space-md;
  padding-bottom: calc(#{$space-xl} + env(safe-area-inset-bottom));

  // 1. 状态 tabs
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

  &__more {
    padding: $space-md 0;
    font-size: $t-22;
    color: $text-3;
    text-align: center;
  }
}

// 3. 订单卡片
.o-card {
  padding: $space-lg;
  margin-bottom: $space-md;
  background: $card;
  border-radius: $radius;
  box-shadow: $shadow;

  &__head {
    @include flex-between;

    margin-bottom: $space-sm;
  }

  &__merchant {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    font-size: $t-28;
    font-weight: 500;
    color: $text-1;
    white-space: nowrap;
    text-overflow: ellipsis;
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
      color: $text-2;
    }

    &--4,
    &--5 {
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

  // 右操作区：已优惠文案 + 继续支付 / 申请退款
  &__ops {
    display: flex;
    flex: none;
    align-items: center;
    gap: $space-xs;
  }

  &__time {
    flex: 1;
    font-size: $t-22;
    color: $text-3;
  }

  &__save {
    flex: none;
    font-size: $t-22;
    color: $danger;
  }

  // 核销码大字号展示（点击待核销卡展开）
  &__redeem {
    @include flex-center(column);

    padding: $space-md 0 $space-xs;
    margin-top: $space-sm;
    background: rgba($brand, 0.06);
    border: 1rpx dashed $brand;
    border-radius: $radius-sm;
  }

  &__redeem-label {
    margin-bottom: $space-xs;
    font-size: $t-22;
    color: $text-2;
  }

  &__redeem-code {
    font-family: $font-family;
    font-size: 56rpx;
    font-weight: 700;
    color: $brand-dark;
    letter-spacing: 8rpx;
  }
}
</style>
