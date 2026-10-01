<template>
  <view class="detail">
    <!-- 1. 商家头图占位（cover_url 多为空，渐变块占位） -->
    <view class="detail__hero" :class="{ 'detail__hero--img': !!mer?.cover_url }">
      <image
        v-if="mer?.cover_url"
        class="detail__hero-img"
        :src="mer.cover_url"
        mode="aspectFill"
        @error="mer.cover_url = null"
      />
      <image v-else class="detail__hero-img" src="/static/merchant-default.png" mode="aspectFill" />
    </view>

    <CSkeleton v-if="loading" :rows="4" class="detail__body" />
    <template v-else-if="mer">
      <!-- 2. Mock 兜底标注 -->
      <view v-if="isMock" class="detail__mock-tip">示例数据 · 后端暂未连接</view>

      <!-- 3. 商家信息卡：名称/评分/类目/地址/电话 -->
      <view class="info">
        <view class="info__head">
          <text class="info__name">{{ mer.name }}</text>
          <text
            class="info__status"
            :class="{ 'info__status--closed': mer.status !== 1 }"
          >
            {{ mer.status === 1 ? '营业中' : '已停业' }}
          </text>
        </view>
        <view class="info__meta">
          <view class="info__rating">
            <image class="info__star" src="/static/icons/ic-star.png" mode="aspectFit" />
            <text>{{ mer.rating.toFixed(1) }}</text>
          </view>
          <text class="info__cat">{{ mer.category }}</text>
          <text v-if="mer.distance_m != null" class="info__dist">
            {{ mer.distance_m < 1000 ? `${mer.distance_m}m` : `${(mer.distance_m / 1000).toFixed(1)}km` }}
          </text>
        </view>
        <view v-if="mer.address" class="info__row">
          <image class="info__row-icon" src="/static/icons/ic-pin.png" mode="aspectFit" />
          <text class="info__row-text">{{ mer.address }}</text>
        </view>
        <view v-if="mer.phone" class="info__row" @tap="callMerchant">
          <image class="info__row-icon" src="/static/icons/ic-phone.png" mode="aspectFit" />
          <text class="info__row-text info__row-text--link">{{ mer.phone }}</text>
          <text class="info__row-action">拨打</text>
        </view>
      </view>

      <!-- 4. 在售 SKU：名称/价格/库存 + 数量加减 -->
      <view class="skus">
        <view class="skus__title">在售套餐</view>
        <CEmpty v-if="!mer.skus.length" icon="empty-order" text="商家暂未上架套餐" button-text="" />
        <view v-for="sku in mer.skus" :key="sku.id" class="sku">
          <view class="sku__main">
            <text class="sku__name">{{ sku.name }}</text>
            <text class="sku__meta">
              ¥{{ sku.price }}
              <text v-if="sku.stock < 0"> · 不限量</text>
              <text v-else-if="sku.stock === 0"> · 已售罄</text>
              <text v-else> · 剩 {{ sku.stock }} 份</text>
            </text>
          </view>

          <!-- 已售罄禁选；否则数量加减 -->
          <view v-if="sku.stock === 0" class="sku__soldout">售罄</view>
          <view v-else class="stepper">
            <view
              class="stepper__btn"
              :class="{ 'stepper__btn--off': !qtyOf(sku.id) }"
              @tap="changeQty(sku, -1)"
            >
              −
            </view>
            <text class="stepper__num">{{ qtyOf(sku.id) }}</text>
            <view
              class="stepper__btn"
              :class="{ 'stepper__btn--off': qtyOf(sku.id) >= qtyMax(sku) }"
              @tap="changeQty(sku, 1)"
            >
              +
            </view>
          </view>
        </view>
      </view>

      <!-- 5. 底部下单栏 -->
      <view class="detail__bar">
        <view class="detail__bar-main">
          <text class="detail__bar-count">已选 {{ totalQty }} 件</text>
          <text class="detail__bar-total">¥{{ totalAmount.toFixed(2) }}</text>
        </view>
        <CButton size="md" :disabled="!totalQty" @click="goConfirm">去下单</CButton>
      </view>
    </template>
    <CError v-else text="商家不存在或已下架" button-text="" />
  </view>
</template>

<script setup lang="ts">
/**
 * FE4 · 商家详情 — Phase 3 (M3)
 * 依据：docs/split/03-页面布局与交互说明.md §5.2-7 商家卡 [查看详情] 落地页
 * 契约：GET /api/merchant/{id}（MerchantDetail，含在售 SKU）
 * 【假设】后端尚未部署联调：请求失败时回退内置示例商家（与列表页 mock 同源 id），
 *         保证页面结构与双端 build 完整。
 */
import { computed, ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { getMerchantDetail } from '@/api/merchant'
import { track } from '@/utils/track'
import type { MerchantDetail, SkuOut } from '@/types/api'

/** 每 SKU 选择上限（不限量 SKU 统一按 9 件封顶，防误触） */
const QTY_CAP = 9

/* ---------- Mock 兜底数据（结构对齐 MerchantDetail，id 与列表页 mock 对齐） ---------- */

const MOCK_DETAILS: MerchantDetail[] = [
  {
    id: 101, name: '轻食盒子（科技园店）', category: '轻食', distance_m: 450, rating: 4.8,
    cover_url: null, status: 1, partner_level: 2, phone: '0755-88881001',
    address: '南山区科技园南区 A 座 1 层',
    skus: [
      { id: 1, name: '高蛋白餐（鸡胸/牛肉任选）', price: 28, stock: 50 },
      { id: 2, name: '低卡藜麦沙拉碗', price: 25, stock: 32 },
      { id: 3, name: '全麦三明治套餐', price: 22, stock: -1 },
    ],
  },
  {
    id: 103, name: '超级猩猩健身（南山店）', category: '健身房', distance_m: 1200, rating: 4.7,
    cover_url: null, status: 1, partner_level: 1, phone: '0755-88882003',
    address: '南山区海岸城 3 层',
    skus: [
      { id: 11, name: '单次团课（操课/单车）', price: 50, stock: 20 },
      { id: 12, name: '私教体验课 1 节', price: 99, stock: 8 },
    ],
  },
]

/* ---------- 状态 ---------- */

const mer = ref<MerchantDetail | null>(null)
const loading = ref(true)
const isMock = ref(false)
/** sku_id → qty 的已选映射 */
const selected = ref<Record<number, number>>({})

const totalQty = computed(() =>
  Object.values(selected.value).reduce((sum, n) => sum + n, 0),
)
const totalAmount = computed(() => {
  if (!mer.value) return 0
  return mer.value.skus.reduce(
    (sum, sku) => sum + (selected.value[sku.id] || 0) * sku.price,
    0,
  )
})

/* ---------- 工具 ---------- */

function qtyOf(skuId: number): number {
  return selected.value[skuId] || 0
}

/** stock=-1 不限量 → QTY_CAP；否则 stock（下限 1 防 0/负） */
function qtyMax(sku: SkuOut): number {
  return sku.stock < 0 ? QTY_CAP : Math.max(1, sku.stock)
}

function changeQty(sku: SkuOut, delta: number) {
  const next = qtyOf(sku.id) + delta
  if (next < 0) return
  if (next > qtyMax(sku)) return
  selected.value = { ...selected.value, [sku.id]: next }
}

function callMerchant() {
  if (!mer.value?.phone) return
  uni.makePhoneCall({ phoneNumber: mer.value.phone })
}

/* ---------- 数据加载 ---------- */

async function loadDetail(id: number) {
  loading.value = true
  try {
    mer.value = await getMerchantDetail(id)
    isMock.value = false
  } catch (e) {
    // request 层已统一 toast；兜底内置示例商家（找不到同 id 时取第一条）
    mer.value = MOCK_DETAILS.find((m) => m.id === id) || MOCK_DETAILS[0]
    isMock.value = true
  } finally {
    loading.value = false
  }
}

/* ---------- 跳转订单确认 ---------- */

function goConfirm() {
  if (!mer.value || !totalQty.value) return
  const items = mer.value.skus
    .filter((sku) => qtyOf(sku.id) > 0)
    .map((sku) => ({ sku_id: sku.id, name: sku.name, price: sku.price, qty: qtyOf(sku.id) }))
  const query = [
    `merchant_id=${mer.value.id}`,
    `merchant_name=${encodeURIComponent(mer.value.name)}`,
    `category=${encodeURIComponent(mer.value.category)}`,
    `items=${encodeURIComponent(JSON.stringify(items))}`,
  ].join('&')
  uni.navigateTo({ url: `/pages/order/confirm?${query}` })
}

/* ---------- 生命周期 ---------- */

onLoad((options) => {
  const opt = options as { id?: string; scene?: string } | undefined
  const id = Number(opt?.id) || MOCK_DETAILS[0].id
  // 扫码转化率（分母）：扫码（商家码/券码）进入，带 merchant_id + scene
  if (opt?.scene) {
    track('scan_in', { merchant_id: id, scene: decodeURIComponent(opt.scene) })
  }
  void loadDetail(id)
})
</script>

<style lang="scss" scoped>
.detail {
  padding-bottom: calc(160rpx + env(safe-area-inset-bottom));

  // 1. 头图占位（渐变底 + emoji）
  &__hero {
    @include flex-center;

    height: 320rpx;
    background: linear-gradient(135deg, rgba(34, 197, 94, 0.18), rgba(34, 197, 94, 0.05));

    &--img {
      background: none;
    }
  }

  &__hero-img {
    width: 100%;
    height: 100%;
  }

  &__body {
    margin: $space-md;
  }

  // 2. Mock 兜底标注
  &__mock-tip {
    padding: $space-sm $space-md;
    margin: $space-md $space-md 0;
    font-size: $t-22;
    color: $warn;
    text-align: center;
    background: rgba(245, 158, 11, 0.1);
    border-radius: $radius-sm;
  }

  // 5. 底部下单栏（fixed，§4 常用底部操作栏形态）
  &__bar {
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
  }

  &__bar-main {
    flex: 1;
    min-width: 0;
  }

  &__bar-count {
    display: block;
    font-size: $t-22;
    color: $text-2;
  }

  &__bar-total {
    font-size: $t-num-lg;
    font-weight: 700;
    color: $brand;
  }
}

// 3. 商家信息卡
.info {
  padding: $space-lg;
  margin: $space-md;
  background: $card;
  border-radius: $radius;
  box-shadow: $shadow;

  &__head {
    @include flex-between;

    margin-bottom: $space-xs;
  }

  &__name {
    flex: 1;
    min-width: 0;
    font-size: $t-32;
    font-weight: 700;
    color: $text-1;
  }

  &__status {
    flex: none;
    margin-left: $space-sm;
    font-size: $t-22;
    color: $success;

    &--closed {
      color: $text-3;
    }
  }

  &__meta {
    display: flex;
    gap: $space-md;
    margin-bottom: $space-sm;
  }

  &__rating {
    display: flex;
    align-items: center;
    gap: 4rpx;
    font-size: $t-24;
    color: $text-1;
  }

  &__star {
    width: 26rpx;
    height: 26rpx;
  }

  &__cat,
  &__dist {
    font-size: $t-24;
    color: $text-2;
  }

  &__row {
    display: flex;
    align-items: center;
    gap: $space-xs;
    padding: $space-xs 0;
  }

  &__row-icon {
    flex: none;
    width: 32rpx;
    height: 32rpx;
  }

  &__row-text {
    flex: 1;
    min-width: 0;
    font-size: $t-24;
    color: $text-2;

    &--link {
      color: $brand;
    }
  }

  &__row-action {
    flex: none;
    font-size: $t-22;
    color: $brand;
  }
}

// 4. SKU 列表
.skus {
  margin: $space-md;
  background: $card;
  border-radius: $radius;
  box-shadow: $shadow;

  &__title {
    padding: $space-lg $space-lg $space-sm;
    font-size: $t-28;
    font-weight: 500;
    color: $text-1;
  }
}

.sku {
  @include flex-between;

  gap: $space-sm;
  padding: $space-md $space-lg;

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
    font-weight: 500;
    color: $text-1;
  }

  &__meta {
    font-size: $t-22;
    color: $brand-dark;
  }

  &__soldout {
    padding: 8rpx $space-md;
    font-size: $t-22;
    color: $text-3;
    background: $bg;
    border-radius: $radius-sm;
  }
}

// 数量加减步进器
.stepper {
  @include flex-center;

  flex: none;
  gap: $space-sm;

  &__btn {
    @include flex-center;
    @include press;

    width: 52rpx;
    height: 52rpx;
    font-size: $t-28;
    color: $brand;
    background: rgba(34, 197, 94, 0.1);
    border-radius: $radius-sm;

    &--off {
      color: $text-3;
      background: $bg;
    }
  }

  &__num {
    min-width: 48rpx;
    font-size: $t-26;
    font-weight: 500;
    color: $text-1;
    text-align: center;
  }
}
</style>
