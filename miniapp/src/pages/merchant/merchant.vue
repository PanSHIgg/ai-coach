<template>
  <view class="merchant">
    <!-- 1. 类目筛选 chips（全部/轻食/健身房） -->
    <view class="merchant__chips">
      <text
        v-for="cat in CATEGORIES"
        :key="cat"
        class="merchant__chip"
        :class="{ 'merchant__chip--active': cat === activeCategory }"
        @tap="switchCategory(cat)"
      >
        {{ cat }}
      </text>
    </view>

    <!-- 2. Mock 兜底标注（后端未部署/请求失败时展示内置示例数据） -->
    <view v-if="isMock" class="merchant__mock-tip">示例数据 · 后端暂未连接</view>

    <!-- 2b. 自动带券提示（§3.3 不限商家券从此页自选商家下单，券随跳转透传） -->
    <view v-if="couponId" class="merchant__coupon-tip">已带优惠券 · 选商家后自动带入下单页</view>

    <!-- 3. 商家列表：名称/类目/评分/距离（§5.1 商家比价入口） -->
    <CSkeleton v-if="loading && !list.length" type="card" />
    <CEmpty
      v-else-if="!list.length"
      icon="empty-store"
      text="附近商家正在入驻"
      button-text=""
    />
    <template v-else>
      <view
        v-for="m in list"
        :key="m.id"
        class="m-card"
        @tap="goDetail(m.id)"
      >
        <!-- 头图（cover_url 多为空 → 品牌默认插画；外链失败 @error 回退） -->
        <view class="m-card__cover">
          <image
            v-if="m.cover_url"
            class="m-card__img"
            :src="m.cover_url"
            mode="aspectFill"
            @error="m.cover_url = null"
          />
          <image v-else class="m-card__img" src="/static/merchant-default.png" mode="aspectFill" />
        </view>

        <view class="m-card__main">
          <view class="m-card__head">
            <text class="m-card__name">{{ m.name }}</text>
            <text
              class="m-card__status"
              :class="{ 'm-card__status--closed': m.status !== 1 }"
            >
              {{ m.status === 1 ? '营业中' : '已停业' }}
            </text>
          </view>
          <view class="m-card__meta">
            <text class="m-card__cat">{{ m.category }}</text>
            <view class="m-card__rating">
              <image class="m-card__star" src="/static/icons/ic-star.png" mode="aspectFit" />
              <text>{{ m.rating.toFixed(1) }}</text>
            </view>
          </view>
          <text class="m-card__dist">{{ fmtDist(m.distance_m) }}</text>
        </view>
      </view>

      <view v-if="loading" class="merchant__more">加载中...</view>
      <view v-else-if="!hasMore" class="merchant__more">没有更多了</view>
    </template>
  </view>
</template>

<script setup lang="ts">
/**
 * FE4 · 商家列表（tab 壳页）— Phase 3 (M3)
 * 依据：docs/split/03-页面布局与交互说明.md §5.1 商家比价 / 首页·券提醒 [去使用] 落地页
 *       §3.3 券包 → 不限商家可用券落此页自选商家：读 coupon_id 并透传给详情页
 * 契约：GET /api/merchant/list（MerchantPageData）
 * 【假设】后端尚未部署联调：请求失败（开发态无后端）时回退内置示例数据并标注，
 *         保证页面结构与双端 build 完整；联调后自然切换为真数据。
 */
import { ref } from 'vue'
import { onLoad, onReachBottom } from '@dcloudio/uni-app'
import { getMerchants } from '@/api/merchant'
import type { MerchantBrief } from '@/types/api'

const CATEGORIES = ['全部', '轻食', '健身房'] as const
const PAGE_SIZE = 10

/* ---------- Mock 兜底数据（结构对齐 MerchantBrief） ---------- */

const MOCK_MERCHANTS: MerchantBrief[] = [
  { id: 101, name: '轻食盒子（科技园店）', category: '轻食', distance_m: 450, rating: 4.8, cover_url: null, status: 1, partner_level: 2 },
  { id: 102, name: '能量沙拉 LAB', category: '轻食', distance_m: 900, rating: 4.6, cover_url: null, status: 1, partner_level: 1 },
  { id: 103, name: '超级猩猩健身（南山店）', category: '健身房', distance_m: 1200, rating: 4.7, cover_url: null, status: 1, partner_level: 1 },
  { id: 104, name: '乐刻运动 SPACE', category: '健身房', distance_m: 1600, rating: 4.5, cover_url: null, status: 1, partner_level: 0 },
  { id: 105, name: '谷雨轻食简餐', category: '轻食', distance_m: 2100, rating: 4.4, cover_url: null, status: 1, partner_level: 0 },
  { id: 106, name: '中田健身工作室', category: '健身房', distance_m: 2600, rating: 4.9, cover_url: null, status: 0, partner_level: 0 },
]

/* ---------- 状态 ---------- */

const activeCategory = ref<string>('全部')
const list = ref<MerchantBrief[]>([])
const page = ref(1)
const hasMore = ref(false)
const loading = ref(false)
const isMock = ref(false)
const userLat = ref<number | null>(null)
const userLng = ref<number | null>(null)
/**
 * 券包带过来的券 id（§3.3「券包 → 点击可用券 → 下单页（自动带券）」）：
 * 不限商家券落到本页自选商家，此处只负责读取 + 继续透传给详情页，不做可用性判断。
 */
const couponId = ref<number | null>(null)

/* ---------- 工具 ---------- */

/** 解析 coupon_id：缺失 / 非数字 / 非正数 → null（退化为「未带券」的正常流程，不崩不白屏） */
function parseCouponId(raw?: string): number | null {
  const n = Number(raw)
  return Number.isInteger(n) && n > 0 ? n : null
}

/** 距离格式化：米 <1000 显示 m，否则 km（字段可空） */
function fmtDist(distanceM?: number | null): string {
  if (distanceM == null) return '距离未知'
  return distanceM < 1000 ? `${distanceM}m` : `${(distanceM / 1000).toFixed(1)}km`
}

/* ---------- 数据加载 ---------- */

async function loadPage(reset: boolean) {
  if (loading.value) return
  loading.value = true
  if (reset) {
    page.value = 1
  }
  try {
    const data = await getMerchants({
      page: page.value,
      page_size: PAGE_SIZE,
      ...(activeCategory.value === '全部' ? {} : { category: activeCategory.value }),
      // 拿到定位才传坐标：后端距离/权重排序生效
      ...(userLat.value != null && userLng.value != null
        ? { lat: userLat.value, lng: userLng.value }
        : {}),
    })
    const items = data?.items ?? []
    list.value = reset ? items : [...list.value, ...items]
    const total = data?.page?.total ?? 0
    hasMore.value = list.value.length < total
    isMock.value = false
  } catch (e) {
    // request 层已统一 toast；此处兜底内置示例数据（后端未部署时保证页面可看）
    if (reset) {
      list.value = MOCK_MERCHANTS.filter(
        (m) => activeCategory.value === '全部' || m.category === activeCategory.value,
      )
    }
    hasMore.value = false
    isMock.value = true
  } finally {
    loading.value = false
  }
}

function switchCategory(cat: string) {
  if (cat === activeCategory.value) return
  activeCategory.value = cat
  void loadPage(true)
}

function goDetail(id: number) {
  const parts = [`id=${id}`]
  // 自动带券（§3.3）：券 id 继续往详情页透传，最终由订单确认页选中/灰显
  if (couponId.value != null) parts.push(`coupon_id=${couponId.value}`)
  uni.navigateTo({ url: `/pages/merchant/detail?${parts.join('&')}` })
}

/* ---------- 生命周期 ---------- */

onLoad((options) => {
  couponId.value = parseCouponId((options as { coupon_id?: string } | undefined)?.coupon_id)
  // 尝试取定位（gcj02；fail 静默降级为无坐标查询），成败都先加载列表
  uni.getLocation({
    type: 'gcj02',
    success: (res) => {
      userLat.value = res.latitude
      userLng.value = res.longitude
    },
    fail: () => {},
    complete: () => void loadPage(true),
  })
})

onReachBottom(() => {
  if (!hasMore.value || loading.value) return
  page.value += 1
  void loadPage(false)
})
</script>

<style lang="scss" scoped>
.merchant {
  padding: $space-md;
  padding-bottom: calc(#{$space-xl} + env(safe-area-inset-bottom));

  // 1. 类目筛选 chips（§5.2 chips 样式约定：绿底浅色 + 深绿字）
  &__chips {
    display: flex;
    gap: $space-sm;
    margin-bottom: $space-md;
  }

  &__chip {
    padding: 8rpx $space-md;
    font-size: $t-24;
    color: $text-2;
    background: $card;
    border: 1rpx solid $border;
    border-radius: $radius-sm;

    &--active {
      color: $brand-dark;
      background: rgba($brand, 0.1);
      border-color: $brand;
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

  // 2b. 自动带券提示（§3.3 不限商家券：本页自选商家，券随跳转透传到下单页）
  &__coupon-tip {
    padding: $space-sm $space-md;
    margin-bottom: $space-md;
    font-size: $t-22;
    color: $brand-dark;
    text-align: center;
    background: rgba($brand, 0.1);
    border-radius: $radius-sm;
  }

  &__more {
    padding: $space-md 0;
    font-size: $t-22;
    color: $text-3;
    text-align: center;
  }
}

// 3. 商家卡片（§4.11 卡片：左头图 + 右信息）
.m-card {
  display: flex;
  gap: $space-md;
  padding: $space-md;
  margin-bottom: $space-md;
  background: $card;
  border-radius: $radius;
  box-shadow: $shadow;

  &__cover {
    @include flex-center;

    flex: none;
    width: 140rpx;
    height: 140rpx;
    overflow: hidden;
    background: $bg;
    border-radius: $radius-sm;
  }

  &__img {
    width: 100%;
    height: 100%;
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
    font-size: $t-22;
    color: $success;

    &--closed {
      color: $text-3;
    }
  }

  &__meta {
    display: flex;
    gap: $space-md;
    margin-bottom: $space-xs;
  }

  &__cat {
    font-size: $t-24;
    color: $text-2;
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

  &__dist {
    font-size: $t-22;
    color: $text-3;
  }
}
</style>
