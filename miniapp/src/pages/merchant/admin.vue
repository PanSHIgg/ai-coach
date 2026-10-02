<template>
  <view class="ma">
    <!-- 加载 / 错误 全页态 -->
    <CSkeleton v-if="loading && !me" type="card" />
    <CError v-else-if="failed" text="商家数据加载失败" button-text="重试" @retry="loadAll" />

    <template v-else>
      <!-- 1. 商家信息 -->
      <CCard v-if="me">
        <template #title>
          <view class="ma__me-head">
            <text class="ma__me-name">{{ me.name }}</text>
            <text class="ma__me-status" :class="{ 'ma__me-status--off': me.status !== 1 }">
              {{ me.status === 1 ? '营业中' : '已停业' }}
            </text>
          </view>
        </template>
        <template #extra>
          <text class="ma__logout" @tap="onLogout">退出登录</text>
        </template>
        <view class="ma__me-meta">
          <text v-if="me.category" class="ma__me-tag">{{ me.category }}</text>
          <text class="ma__me-tag">{{ partnerText(me.partner_level) }}</text>
          <text class="ma__me-tag">{{ auditText(me.audit_status) }}</text>
        </view>
        <text v-if="me.address" class="ma__me-line">{{ me.address }}</text>
        <text v-if="me.phone" class="ma__me-line">电话：{{ me.phone }}</text>
      </CCard>

      <!-- 2. 数据看板 -->
      <CCard title="数据看板">
        <view class="ma__stats">
          <view class="ma__stat">
            <text class="ma__stat-num">{{ stats?.order_count ?? 0 }}</text>
            <text class="ma__stat-label">订单数</text>
          </view>
          <view class="ma__stat">
            <text class="ma__stat-num">{{ stats?.redeem_count ?? 0 }}</text>
            <text class="ma__stat-label">核销数</text>
          </view>
          <view class="ma__stat">
            <text class="ma__stat-num">¥{{ fmtMoney(stats?.gmv ?? 0) }}</text>
            <text class="ma__stat-label">销售额</text>
          </view>
        </view>
      </CCard>

      <!-- 3. 选品 / 定价 / 上下架 -->
      <CCard title="选品与定价">
        <CEmpty
          v-if="!skus.length"
          icon="empty-store"
          text="暂无可售标准套餐"
          button-text=""
        />
        <template v-else>
          <view v-for="s in skus" :key="s.sku_id" class="ma__sku">
            <view class="ma__sku-head">
              <text class="ma__sku-name">{{ s.catalog_name }}</text>
              <text class="ma__sku-status" :class="{ 'ma__sku-status--off': s.status !== 1 }">
                {{ s.status === 1 ? '已上架' : '已下架' }}
              </text>
            </view>
            <text class="ma__sku-range">
              目录限价 ¥{{ fmtMoney(s.min_price) }} ~ ¥{{ fmtMoney(s.max_price) }}
            </text>
            <view class="ma__sku-ops">
              <view class="ma__sku-price">
                <text class="ma__sku-price-label">售价 ¥</text>
                <CInput
                  v-model="prices[s.sku_id]"
                  type="digit"
                  placeholder="区间内定价"
                  :maxlength="10"
                />
              </view>
              <CButton size="sm" :loading="savingSkuId === s.sku_id" @click="savePrice(s)">
                保存
              </CButton>
              <CButton
                size="sm"
                type="secondary"
                :loading="togglingSkuId === s.sku_id"
                @click="toggleSku(s)"
              >
                {{ s.status === 1 ? '下架' : '上架' }}
              </CButton>
            </view>
          </view>
        </template>
      </CCard>

      <!-- 4. 订单 / 核销 -->
      <CCard title="订单与核销">
        <template #extra>
          <view class="ma__filter">
            <text
              v-for="f in ORDER_FILTERS"
              :key="f.label"
              class="ma__filter-item"
              :class="{ 'ma__filter-item--active': orderFilter === f.value }"
              @tap="switchOrderFilter(f.value)"
            >
              {{ f.label }}
            </text>
          </view>
        </template>

        <CSkeleton v-if="ordersLoading && !orders.length" type="line" :rows="3" />
        <CEmpty
          v-else-if="!orders.length"
          icon="empty-order"
          text="暂无订单"
          button-text=""
        />
        <template v-else>
          <view v-for="o in orders" :key="o.id" class="ma__order">
            <view class="ma__order-head">
              <text class="ma__order-no">{{ o.order_no }}</text>
              <text class="ma__order-status">{{ orderStatusText(o.status) }}</text>
            </view>
            <view class="ma__order-meta">
              <text>金额 ¥{{ fmtMoney(o.pay_amount ?? o.total_amount ?? 0) }}</text>
              <text>{{ fmtTime(o.created_at) }}</text>
            </view>
            <view class="ma__order-foot">
              <text v-if="o.redeem_code" class="ma__order-code">核销码 {{ o.redeem_code }}</text>
              <text v-else class="ma__order-code">—</text>
              <CButton
                v-if="o.status === 2"
                size="sm"
                :loading="redeemingId === o.id"
                @click="onRedeem(o)"
              >
                核销
              </CButton>
            </view>
          </view>
        </template>
        <view v-if="orders.length" class="ma__more">
          <text v-if="ordersLoading">加载中...</text>
          <text v-else-if="ordersHasMore" @tap="loadOrders(false)">加载更多</text>
          <text v-else>没有更多了</text>
        </view>
      </CCard>
    </template>
  </view>
</template>

<script setup lang="ts">
/**
 * G11 · 商家后台
 * 依据：docs/split/01-整体架构与产品需求.md L160（页面 25 商家后台：选品、定价、选券、上下架、核销、数据）
 * 契约：api/merchantAdmin.ts（GET me/skus/orders/stats、PUT skus、POST toggle/redeem）
 * 【假设】「选券」在冻结契约中无对应商家自助接口 → 未实现（见汇报）。
 * 商家 token 缺失 / 401 → 清商家 token 并回登录页。
 */
import { reactive, ref } from 'vue'
import { onReachBottom, onShow } from '@dcloudio/uni-app'
import {
  getMerchantToken,
  clearMerchantToken,
  getMerchantMe,
  getMerchantSkus,
  updateMerchantSkus,
  toggleMerchantSku,
  getMerchantOrders,
  redeemMerchantOrder,
  getMerchantStats,
} from '@/api/merchantAdmin'
import type {
  MerchantMeData,
  MerchantSkuItem,
  MerchantOrderItem,
  MerchantStatsData,
} from '@/types/api'
import { useToast } from '@/composables/useToast'

/** 错误码常量（types/api.d.ts 的 ErrorCode 非运行时模块，按 request.ts 约定硬编码） */
const CODE_UNAUTHORIZED = 1001
const CODE_REDEEM_USED = 5004

const toast = useToast()
const PAGE_SIZE = 20

/** 订单状态过滤项（undefined = 全部） */
const ORDER_FILTERS: { label: string; value: number | null }[] = [
  { label: '全部', value: null },
  { label: '待核销', value: 2 },
  { label: '已完成', value: 3 },
]

/* ---------- 状态 ---------- */
const me = ref<MerchantMeData | null>(null)
const skus = ref<MerchantSkuItem[]>([])
const stats = ref<MerchantStatsData | null>(null)
const orders = ref<MerchantOrderItem[]>([])
/** 定价草稿：sku_id → 输入字符串 */
const prices = reactive<Record<number, string>>({})

const loading = ref(false)
const failed = ref(false)
const ordersLoading = ref(false)
const ordersHasMore = ref(false)
const ordersPage = ref(1)
const orderFilter = ref<number | null>(null)

const savingSkuId = ref(-1)
const togglingSkuId = ref(-1)
const redeemingId = ref(-1)

/* ---------- 工具 ---------- */

function isUnauthorized(e: unknown): boolean {
  return (e as { code?: number })?.code === CODE_UNAUTHORIZED
}

/** 商家登录态失效：清商家 token（不动用户登录态）并回商家登录页 */
function toMerchantLogin(): void {
  clearMerchantToken()
  uni.reLaunch({ url: '/pages/merchant/login' })
}

function fmtMoney(n: number): string {
  return n.toFixed(2)
}

/** ISO 时间 → MM-DD HH:mm */
function fmtTime(iso: string): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const p = (v: number) => String(v).padStart(2, '0')
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

const ORDER_STATUS_TEXT: Record<number, string> = {
  1: '待支付',
  2: '待核销',
  3: '已完成',
  4: '已取消',
  5: '已退款',
}
const AUDIT_TEXT: Record<number, string> = { 0: '待审核', 1: '已通过', 2: '已驳回' }
const PARTNER_TEXT: Record<number, string> = { 0: '普通商家', 1: '优选合作', 2: '战略合作' }

function orderStatusText(status: number): string {
  return ORDER_STATUS_TEXT[status] ?? '未知'
}

function auditText(s: number): string {
  return AUDIT_TEXT[s] ?? '—'
}

function partnerText(level: number): string {
  return PARTNER_TEXT[level] ?? '—'
}

/** 定价草稿回填（列表刷新后重置为服务端价） */
function applyPrices(): void {
  skus.value.forEach((s) => {
    prices[s.sku_id] = String(s.price)
  })
}

/* ---------- 数据加载 ---------- */

async function loadAll(): Promise<void> {
  if (loading.value) return
  if (!getMerchantToken()) {
    toMerchantLogin()
    return
  }
  loading.value = true
  failed.value = false
  try {
    const [meData, skuData, statsData] = await Promise.all([
      getMerchantMe(true),
      getMerchantSkus(true),
      getMerchantStats(true),
    ])
    me.value = meData
    skus.value = skuData.items ?? []
    stats.value = statsData
    applyPrices()
  } catch (e) {
    if (isUnauthorized(e)) {
      toMerchantLogin()
      return
    }
    failed.value = true
    toast.error({ title: (e as Error).message || '加载失败' })
  } finally {
    loading.value = false
  }
  if (!failed.value) await loadOrders(true)
}

async function loadOrders(reset: boolean): Promise<void> {
  if (ordersLoading.value) return
  ordersLoading.value = true
  if (reset) ordersPage.value = 1
  try {
    const data = await getMerchantOrders(
      {
        page: ordersPage.value,
        page_size: PAGE_SIZE,
        ...(orderFilter.value == null ? {} : { status: orderFilter.value }),
      },
      true,
    )
    const items = data?.items ?? []
    orders.value = reset ? items : [...orders.value, ...items]
    const total = data?.page?.total ?? 0
    ordersHasMore.value = orders.value.length < total
  } catch (e) {
    if (isUnauthorized(e)) {
      toMerchantLogin()
      return
    }
    if (reset) orders.value = []
    ordersHasMore.value = false
    toast.error({ title: (e as Error).message || '订单加载失败' })
  } finally {
    ordersLoading.value = false
  }
}

function switchOrderFilter(value: number | null): void {
  if (orderFilter.value === value) return
  orderFilter.value = value
  void loadOrders(true)
}

/* ---------- 定价 / 上下架 ---------- */

async function savePrice(s: MerchantSkuItem): Promise<void> {
  if (savingSkuId.value !== -1) return
  const raw = (prices[s.sku_id] ?? '').trim()
  const price = Number(raw)
  if (!raw || Number.isNaN(price) || price <= 0) {
    toast.error({ title: '请输入有效价格' })
    return
  }
  // 区间校验（越界前端拦截；服务端另有 code=2001）
  if (price < s.min_price || price > s.max_price) {
    toast.error({
      title: `定价需在 ¥${fmtMoney(s.min_price)} ~ ¥${fmtMoney(s.max_price)} 之间`,
    })
    return
  }
  savingSkuId.value = s.sku_id
  try {
    const data = await updateMerchantSkus([{ sku_id: s.sku_id, price, listed: s.status === 1 }], true)
    skus.value = data.items ?? skus.value
    applyPrices()
    toast.success({ title: '定价已保存' })
  } catch (e) {
    if (isUnauthorized(e)) {
      toMerchantLogin()
      return
    }
    toast.error({ title: (e as Error).message || '保存失败' })
  } finally {
    savingSkuId.value = -1
  }
}

async function toggleSku(s: MerchantSkuItem): Promise<void> {
  if (togglingSkuId.value !== -1) return
  togglingSkuId.value = s.sku_id
  try {
    const data = await toggleMerchantSku(s.sku_id, true)
    s.status = data.status
    toast.success({ title: data.status === 1 ? '已上架' : '已下架' })
  } catch (e) {
    if (isUnauthorized(e)) {
      toMerchantLogin()
      return
    }
    toast.error({ title: (e as Error).message || '操作失败' })
  } finally {
    togglingSkuId.value = -1
  }
}

/* ---------- 核销 ---------- */

function onRedeem(o: MerchantOrderItem): void {
  if (redeemingId.value !== -1) return
  uni.showModal({
    title: '确认核销',
    content: `确认核销订单 ${o.order_no} 吗？核销后不可撤销。`,
    confirmText: '确认核销',
    success: (res) => {
      if (res.confirm) void doRedeem(o)
    },
  })
}

async function doRedeem(o: MerchantOrderItem): Promise<void> {
  redeemingId.value = o.id
  try {
    const data = await redeemMerchantOrder(o.id, true)
    o.status = data.status
    o.redeemed_at = data.redeemed_at
    toast.success({ title: '核销成功' })
    void refreshStats()
  } catch (e) {
    if (isUnauthorized(e)) {
      toMerchantLogin()
      return
    }
    if ((e as { code?: number }).code === CODE_REDEEM_USED) {
      toast.error({ title: '该核销码已使用' })
    } else {
      toast.error({ title: (e as Error).message || '核销失败' })
    }
  } finally {
    redeemingId.value = -1
    void loadOrders(true)
  }
}

async function refreshStats(): Promise<void> {
  try {
    stats.value = await getMerchantStats(true)
  } catch {
    // 看板刷新失败不阻断主流程
  }
}

/* ---------- 退出 ---------- */

function onLogout(): void {
  uni.showModal({
    title: '退出登录',
    content: '确认退出商家后台吗？',
    confirmText: '退出',
    success: (res) => {
      if (res.confirm) toMerchantLogin()
    },
  })
}

/* ---------- 生命周期 ---------- */

onShow(() => void loadAll())

onReachBottom(() => {
  if (!ordersHasMore.value || ordersLoading.value) return
  ordersPage.value += 1
  void loadOrders(false)
})
</script>

<style lang="scss" scoped>
.ma {
  padding: $space-md;
  padding-bottom: calc(#{$space-xl} + env(safe-area-inset-bottom));

  // 1. 商家信息
  &__me-head {
    display: flex;
    align-items: center;
    gap: $space-sm;
  }

  &__me-name {
    font-size: $t-28;
    font-weight: 500;
    color: $text-1;
  }

  &__me-status {
    font-size: $t-22;
    color: $success;

    &--off {
      color: $text-3;
    }
  }

  &__logout {
    font-size: $t-22;
    color: $text-3;
  }

  &__me-meta {
    display: flex;
    flex-wrap: wrap;
    gap: $space-xs;
    margin-bottom: $space-xs;
  }

  &__me-tag {
    padding: 4rpx 12rpx;
    font-size: $t-22;
    color: $brand-dark;
    background: rgba($brand, 0.1);
    border-radius: $radius-sm;
  }

  &__me-line {
    display: block;
    margin-top: $space-xs;
    font-size: $t-24;
    color: $text-2;
  }

  // 2. 数据看板
  &__stats {
    display: flex;
  }

  &__stat {
    flex: 1;
    text-align: center;
  }

  &__stat-num {
    display: block;
    font-size: $t-num-md;
    font-weight: 700;
    color: $text-1;
  }

  &__stat-label {
    display: block;
    margin-top: $space-xs;
    font-size: $t-22;
    color: $text-3;
  }

  // 3. 选品 / 定价
  &__sku {
    padding: $space-md 0;
    border-top: 1rpx solid $border;

    &:first-of-type {
      border-top: none;
    }
  }

  &__sku-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  &__sku-name {
    font-size: $t-26;
    color: $text-1;
  }

  &__sku-status {
    font-size: $t-22;
    color: $success;

    &--off {
      color: $text-3;
    }
  }

  &__sku-range {
    display: block;
    margin-top: $space-xs;
    font-size: $t-22;
    color: $text-3;
  }

  &__sku-ops {
    display: flex;
    align-items: center;
    gap: $space-sm;
    margin-top: $space-sm;
  }

  &__sku-price {
    display: flex;
    flex: 1;
    align-items: center;
    min-width: 0;
    gap: 4rpx;
  }

  &__sku-price-label {
    flex: none;
    font-size: $t-24;
    color: $text-2;
  }

  // 4. 订单 / 核销
  &__filter {
    display: flex;
    gap: $space-sm;
  }

  &__filter-item {
    font-size: $t-22;
    color: $text-2;

    &--active {
      color: $brand-dark;
      font-weight: 500;
    }
  }

  &__order {
    padding: $space-md 0;
    border-top: 1rpx solid $border;

    &:first-of-type {
      border-top: none;
    }
  }

  &__order-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  &__order-no {
    font-size: $t-26;
    color: $text-1;
  }

  &__order-status {
    font-size: $t-22;
    color: $brand-dark;
  }

  &__order-meta {
    display: flex;
    justify-content: space-between;
    margin-top: $space-xs;
    font-size: $t-22;
    color: $text-3;
  }

  &__order-foot {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-top: $space-sm;
  }

  &__order-code {
    font-size: $t-24;
    color: $text-2;
  }

  &__more {
    padding: $space-md 0 0;
    font-size: $t-22;
    color: $text-3;
    text-align: center;
  }
}
</style>