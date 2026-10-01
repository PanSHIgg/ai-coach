<template>
  <view class="plan">
    <!-- 1. 当前权益（GET /api/plan/benefit） -->
    <CCard title="当前权益" class="plan__card">
      <template #extra>
        <text class="plan__link" @tap="goOrders">我的订单 ›</text>
      </template>

      <CSkeleton v-if="benefitLoading" :rows="2" />
      <template v-else>
        <view class="plan__tier-row">
          <text class="plan__tier">{{ tierLabel }}</text>
          <text v-if="benefit?.expired" class="plan__expired">已过期</text>
        </view>
        <view class="plan__benefits">
          <view class="plan__benefit">
            <text class="plan__benefit-k">AI 次数</text>
            <text class="plan__benefit-v">{{ timesText(benefit?.ai_times_left) }}</text>
          </view>
          <view class="plan__benefit">
            <text class="plan__benefit-k">真人问诊</text>
            <text class="plan__benefit-v">{{ timesText(benefit?.coach_times_left) }}</text>
          </view>
          <view class="plan__benefit">
            <text class="plan__benefit-k">有效期至</text>
            <text class="plan__benefit-v">{{ validToText }}</text>
          </view>
        </view>
      </template>
    </CCard>

    <!-- 2. 档位选择（GET /api/plan/list；价格服务端唯一真源） -->
    <CCard title="开通会员" class="plan__card">
      <CSkeleton v-if="listLoading" type="card" />
      <CError v-else-if="listError" @retry="loadPlans" />
      <CEmpty v-else-if="!plans.length" icon="empty-crown" text="暂无可选档位" button-text="" />
      <view v-else class="tiers">
        <view
          v-for="p in plans"
          :key="p.tier"
          class="tier"
          :class="{ 'tier--active': selected === p.tier }"
          @tap="select(p.tier)"
        >
          <view class="tier__head">
            <text class="tier__name">{{ p.name }}</text>
            <text v-if="benefit?.tier === p.tier" class="tier__tag">当前</text>
          </view>
          <view class="tier__price-row">
            <text class="tier__price">¥{{ p.price.toFixed(2) }}</text>
            <text class="tier__period">{{ p.valid_days ? `${p.valid_days} 天` : '终身' }}</text>
          </view>
          <text class="tier__desc">
            AI {{ p.ai_times }} 次 · 真人问诊 {{ p.coach_times }} 次
          </text>
          <text v-if="p.description" class="tier__note">{{ p.description }}</text>
        </view>
      </view>
    </CCard>

    <!-- 3. 下单 + 支付（POST /api/plan/order → POST /api/plan/order/{id}/pay） -->
    <view class="plan__foot">
      <CButton block :disabled="!selected" :loading="paying" @click="onBuy">
        {{ buyText }}
      </CButton>
      <text class="plan__tip">支付由微信支付承接；开通后权益立即生效</text>
    </view>
  </view>
</template>

<script setup lang="ts">
/**
 * FE · 会员订阅付费 — G2
 * 依据：current.md §2.1 G2「平台自营 AI+真人教练订阅付费（进阶 29 / 高级 59 / 终身档）」
 *       docs/split/03 §5.8「未开通权益 → [立即开通] 进订阅页」
 * 契约：GET /api/plan/list、GET /api/plan/benefit、POST /api/plan/order、
 *       POST /api/plan/order/{id}/pay、GET /api/plan/orders
 *
 * 【假设】① 金额一律以 /api/plan/list 下发的 price 为准，前端不硬编码（文档价仅作对照）；
 *         ② PAY_MOCK_MODE / H5 下 pay_params 为空对象 → 拿到订单即视为支付成功（模拟），
 *            与 pages/order/confirm.vue 口径一致；小程序端有参数时走 uni.requestPayment；
 *         ③ 支付成功后刷新权益 + userStore.fetchMe()（我的页版本标签同步）。
 */
import { computed, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { useUserStore } from '@/stores/user'
import { useToast } from '@/composables/useToast'
import { redirectToLogin } from '@/utils/nav'
import { track } from '@/utils/track'
import { getPlans, getPlanBenefit, createPlanOrder, payPlanOrder } from '@/api/plan'
import type { PlanBenefitData, PlanTier, PlanTierItem } from '@/types/api'

/** 档位文案（0基础 1进阶 2高级 3终身，与 mine.vue §5.5 一致） */
const TIER_LABEL: Record<number, string> = {
  0: '基础版（免费）',
  1: '进阶版',
  2: '高级版',
  3: '终身版',
}

const userStore = useUserStore()
const toast = useToast()

const plans = ref<PlanTierItem[]>([])
const benefit = ref<PlanBenefitData | null>(null)
const selected = ref<PlanTier | null>(null)

const listLoading = ref(false)
const listError = ref(false)
const benefitLoading = ref(false)
const paying = ref(false)

const tierLabel = computed(() => TIER_LABEL[benefit.value?.tier ?? 0] || '基础版（免费）')

const validToText = computed(() => {
  if (!benefit.value?.valid_to) return (benefit.value?.tier ?? 0) === 3 ? '终身不限期' : '—'
  const d = new Date(benefit.value.valid_to)
  if (Number.isNaN(d.getTime())) return benefit.value.valid_to
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
})

const currentPlan = computed(() => plans.value.find((p) => p.tier === selected.value) || null)

const buyText = computed(() => {
  const p = currentPlan.value
  if (!p) return '请选择档位'
  return `开通${p.name} ¥${p.price.toFixed(2)}`
})

/** 次数文案：null/undefined 视为 0；<0 视为不限次 */
function timesText(n?: number | null): string {
  if (n == null) return '0 次'
  if (n < 0) return '不限次'
  return `${n} 次`
}

/* ---------- 数据加载 ---------- */

async function loadPlans() {
  listLoading.value = true
  listError.value = false
  try {
    const data = await getPlans()
    plans.value = data?.items ?? []
    // 默认选中：当前档位（>0）优先，否则最低档
    const cur = benefit.value?.tier
    const hit = plans.value.find((p) => p.tier === cur)
    selected.value = (hit?.tier as PlanTier | undefined) ?? (plans.value[0]?.tier as PlanTier | undefined) ?? null
  } catch (e) {
    plans.value = []
    listError.value = true
    void e
  } finally {
    listLoading.value = false
  }
}

async function loadBenefit() {
  benefitLoading.value = true
  try {
    benefit.value = (await getPlanBenefit()) ?? null
  } catch (e) {
    benefit.value = null // 失败降级为「基础版」展示，不阻断档位购买
    void e
  } finally {
    benefitLoading.value = false
  }
}

/* ---------- 交互 ---------- */

function select(tier: number) {
  selected.value = tier as PlanTier
}

function goOrders() {
  uni.navigateTo({ url: '/pages/plan/orders' })
}

/**
 * 拉起微信支付。
 * 【假设】仅小程序端能真实拉起；H5/开发态拿到 pay_params 即视为支付成功（模拟）。
 */
function requestWxPay(params: Record<string, unknown>): Promise<void> {
  return new Promise((resolve, reject) => {
    // #ifdef MP-WEIXIN
    uni.requestPayment({
      provider: 'wxpay',
      timeStamp: String(params.timeStamp ?? ''),
      nonceStr: String(params.nonceStr ?? ''),
      package: String(params.package ?? ''),
      signType: String(params.signType ?? ''),
      paySign: String(params.paySign ?? ''),
      success: () => resolve(),
      fail: (err: { errMsg?: string }) => reject(new Error(err?.errMsg || '支付未完成')),
    })
    // #endif
    // #ifndef MP-WEIXIN
    void params
    resolve()
    // #endif
  })
}

/** 下单 → 支付 → 刷新权益 */
async function onBuy() {
  const tier = selected.value
  if (!tier || paying.value) return

  const plan = currentPlan.value
  uni.showModal({
    title: '确认开通',
    content: `${plan?.name || '会员'} ¥${(plan?.price ?? 0).toFixed(2)}，开通后立即生效`,
    confirmText: '确认支付',
    success: (res) => {
      if (res.confirm) void doPay(tier)
    },
  })
}

async function doPay(tier: PlanTier) {
  paying.value = true
  try {
    const order = await createPlanOrder({ tier })
    const payData = await payPlanOrder(order.order_id)
    await requestWxPay((payData?.pay_params ?? {}) as Record<string, unknown>)
    // 会员付费转化（G2 埋点）
    track('plan_pay', { order_id: order.order_id, tier: order.tier, amount: order.pay_amount })
    toast.success({ title: '开通成功' })
    await loadBenefit()
    // 我的页版本标签来自 /api/auth/me 的 benefit，需同步
    if (userStore.isLogined) await userStore.fetchMe()
  } catch (e) {
    // request 已统一 toast（含 5003 订单超时）；支付取消类文案不重复弹错
    const msg = (e as Error)?.message || ''
    if (!msg) toast.info({ title: '支付未完成，可稍后重试' })
  } finally {
    paying.value = false
  }
}

/* ---------- 生命周期 ---------- */

onShow(() => {
  if (!userStore.isLogined) {
    redirectToLogin()
    return
  }
  void loadBenefit().then(loadPlans)
})
</script>

<style lang="scss" scoped>
.plan {
  padding: $space-md;
  padding-bottom: calc(#{$space-xl} + 200rpx + env(safe-area-inset-bottom));

  &__card {
    margin-bottom: $space-md;
  }

  &__link {
    font-size: $t-22;
    color: $brand;
  }

  &__tier-row {
    display: flex;
    align-items: center;
    margin-bottom: $space-sm;
  }

  &__tier {
    font-size: $t-32;
    font-weight: 500;
    color: $text-1;
  }

  &__expired {
    margin-left: $space-sm;
    padding: 2rpx $space-xs;
    font-size: $t-22;
    color: $danger;
    background: rgba(239, 68, 68, 0.1);
    border-radius: $radius-sm;
  }

  &__benefits {
    display: flex;
  }

  &__benefit {
    flex: 1;
    display: flex;
    flex-direction: column;
  }

  &__benefit-k {
    font-size: $t-22;
    color: $text-3;
  }

  &__benefit-v {
    margin-top: 4rpx;
    font-size: $t-26;
    font-weight: 500;
    color: $text-1;
  }

  &__foot {
    position: fixed;
    right: 0;
    bottom: 0;
    left: 0;
    padding: $space-md;
    background: $card;
    border-top: 1rpx solid $border;
    @include safe-area-bottom($space-md);
  }

  &__tip {
    display: block;
    margin-top: $space-sm;
    font-size: $t-22;
    color: $text-3;
    text-align: center;
  }
}

.tiers {
  display: flex;
  flex-direction: column;
  gap: $space-sm;
}

.tier {
  padding: $space-md;
  background: $bg;
  border: 1rpx solid $border;
  border-radius: $radius;

  &--active {
    background: rgba(34, 197, 94, 0.06);
    border-color: $brand;
  }

  &__head {
    display: flex;
    align-items: center;
  }

  &__name {
    font-size: $t-28;
    font-weight: 500;
    color: $text-1;
  }

  &__tag {
    margin-left: $space-sm;
    padding: 2rpx $space-xs;
    font-size: $t-22;
    color: $brand-dark;
    background: rgba(34, 197, 94, 0.1);
    border-radius: $radius-sm;
  }

  &__price-row {
    display: flex;
    align-items: baseline;
    margin-top: $space-xs;
  }

  &__price {
    font-size: $t-num-md;
    font-weight: 700;
    color: $text-1;
  }

  &__period {
    margin-left: $space-xs;
    font-size: $t-22;
    color: $text-2;
  }

  &__desc {
    display: block;
    margin-top: $space-xs;
    font-size: $t-24;
    color: $text-2;
  }

  &__note {
    display: block;
    margin-top: $space-xs;
    font-size: $t-22;
    color: $text-3;
  }
}
</style>
