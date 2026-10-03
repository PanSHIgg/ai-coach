<template>
  <view class="points">
    <!-- 未登录（§5.8 无权限态） -->
    <CNoPermission v-if="!userStore.isLogined" text="登录后查看积分" @action="goLogin" />

    <template v-else>
      <!-- 积分概览 -->
      <CCard class="points__card">
        <CSkeleton v-if="overviewLoading" :rows="2" />
        <template v-else>
          <view class="points__balance">
            <text class="points__balance-num">{{ balance }}</text>
            <text class="points__balance-unit">分</text>
          </view>
          <text class="points__total">累计获得 {{ totalEarned }} 分</text>
        </template>
      </CCard>

      <CCard title="兑换进度" class="points__card">
        <view v-for="t in thresholds" :key="t.points" class="th">
          <view class="th__head">
            <text class="th__reward">{{ t.points }} 分 → {{ t.reward_desc }}</text>
            <text class="th__status" :class="{ 'th__status--ok': balance >= t.points }">
              {{ balance >= t.points ? '可兑换' : `还差 ${t.points - balance} 分` }}
            </text>
          </view>
          <view class="th__bar">
            <view class="th__bar-inner" :style="{ width: `${pct(t.points)}%` }" />
          </view>
        </view>
      </CCard>

      <CCard title="积分明细" class="points__card">
        <CSkeleton v-if="listLoading && !records.length" type="line" :rows="4" />
        <CError v-else-if="listError && !records.length" @retry="() => loadPage(true)" />
        <CEmpty
          v-else-if="!records.length"
          icon="empty-coupon"
          text="还没有积分记录"
          button-text=""
        />
        <template v-else>
          <view v-for="(r, i) in records" :key="i" class="rec">
            <view class="rec__main">
              <text class="rec__reason">{{ r.reason }}</text>
              <text class="rec__time">{{ fmtTime(r.created_at) }}</text>
            </view>
            <text class="rec__change" :class="r.change >= 0 ? 'rec__change--up' : 'rec__change--down'">
              {{ r.change >= 0 ? '+' : '' }}{{ r.change }}
            </text>
          </view>
          <view v-if="listLoading" class="points__more">加载中...</view>
          <view v-else-if="!hasMore" class="points__more">没有更多了</view>
        </template>
      </CCard>
    </template>
  </view>
</template>

<script setup lang="ts">
/**
 * FE · 我的积分 — G3
 * 依据：docs/split/03 §5.5-6 我的积分（当前积分 + 500/800/1500 三档兑换 + 查看积分明细）
 * 契约：GET /api/points（balance/total_earned/thresholds）、GET /api/points/list（分页）
 * 【假设】① 兑换门槛以接口 thresholds 为准，接口为空时回退文档默认三档（500/800/1500）；
 *         ② 本期仅展示兑换进度，兑换动作由商家/券池侧承接（文档未尽，未做兑换按钮）。
 */
import { ref } from 'vue'
import { onShow, onReachBottom } from '@dcloudio/uni-app'
import { useUserStore } from '@/stores/user'
import { redirectToLogin } from '@/utils/nav'
import { getPoints, getPointsList } from '@/api/task'
import type { PointsThreshold, PointsRecordItem } from '@/types/api'

const PAGE_SIZE = 20

/** 文档默认三档（接口未返回 thresholds 时兜底） */
const DEFAULT_THRESHOLDS: PointsThreshold[] = [
  { points: 500, reward_desc: '免费轻食券' },
  { points: 800, reward_desc: '免费运动券' },
  { points: 1500, reward_desc: '50元抵扣券' },
]

const userStore = useUserStore()

const balance = ref(0)
const totalEarned = ref(0)
const thresholds = ref<PointsThreshold[]>(DEFAULT_THRESHOLDS)
const overviewLoading = ref(false)

const records = ref<PointsRecordItem[]>([])
const page = ref(1)
const hasMore = ref(false)
const listLoading = ref(false)
const listError = ref(false)

/** 兑换进度百分比（0-100） */
function pct(points: number): number {
  if (points <= 0) return 0
  return Math.min(100, Math.round((balance.value / points) * 100))
}

function fmtTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

onShow(() => {
  if (!userStore.isLogined) return
  void loadOverview()
  void loadPage(true)
})

async function loadOverview() {
  overviewLoading.value = true
  try {
    const data = await getPoints()
    balance.value = data?.balance ?? 0
    totalEarned.value = data?.total_earned ?? 0
    const list = data?.thresholds ?? []
    thresholds.value = list.length ? list : DEFAULT_THRESHOLDS
  } catch (e) {
    // 失败保留默认门槛展示，不阻断明细
    void e
  } finally {
    overviewLoading.value = false
  }
}

async function loadPage(reset: boolean) {
  if (listLoading.value) return
  listLoading.value = true
  if (reset) {
    page.value = 1
    listError.value = false
  }
  try {
    const data = await getPointsList({ page: page.value, page_size: PAGE_SIZE })
    const items = data?.items ?? []
    records.value = reset ? items : [...records.value, ...items]
    hasMore.value = records.value.length < (data?.page?.total ?? 0)
  } catch (e) {
    if (reset) {
      records.value = []
      listError.value = true
    }
    hasMore.value = false
    void e
  } finally {
    listLoading.value = false
  }
}

onReachBottom(() => {
  if (!hasMore.value || listLoading.value) return
  page.value += 1
  void loadPage(false)
})

function goLogin() {
  redirectToLogin()
}
</script>

<style lang="scss" scoped>
.points {
  padding: $space-md;
  padding-bottom: calc(#{$space-xl} + env(safe-area-inset-bottom));

  &__card {
    margin-bottom: $space-md;
  }

  &__balance {
    display: flex;
    align-items: baseline;
  }

  &__balance-num {
    font-size: $t-num-lg;
    font-weight: 700;
    color: $brand;
  }

  &__balance-unit {
    margin-left: $space-xs;
    font-size: $t-24;
    color: $text-2;
  }

  &__total {
    display: block;
    margin-top: $space-xs;
    font-size: $t-22;
    color: $text-3;
  }

  &__more {
    padding: $space-md 0;
    font-size: $t-22;
    color: $text-3;
    text-align: center;
  }
}

.th {
  padding: $space-sm 0;

  &:not(:last-child) {
    @include hairline(bottom);
  }

  &__head {
    @include flex-between;

    margin-bottom: $space-xs;
  }

  &__reward {
    font-size: $t-26;
    color: $text-1;
  }

  &__status {
    font-size: $t-22;
    color: $text-3;

    &--ok {
      color: $brand;
    }
  }

  &__bar {
    height: 12rpx;
    overflow: hidden;
    background: $bg;
    border-radius: 999rpx;
  }

  &__bar-inner {
    height: 100%;
    background: $brand;
    border-radius: 999rpx;
  }
}

.rec {
  @include flex-between;

  padding: $space-sm 0;

  &:not(:last-child) {
    @include hairline(bottom);
  }

  &__main {
    flex: 1;
    min-width: 0;
    margin-right: $space-sm;
  }

  &__reason {
    display: block;
    font-size: $t-26;
    color: $text-1;
    @include ellipsis;
  }

  &__time {
    display: block;
    margin-top: 4rpx;
    font-size: $t-22;
    color: $text-3;
  }

  &__change {
    flex: none;
    font-size: $t-28;
    font-weight: 500;
    color: $text-1;

    &--up {
      color: $brand;
    }

    &--down {
      color: $danger;
    }
  }
}
</style>