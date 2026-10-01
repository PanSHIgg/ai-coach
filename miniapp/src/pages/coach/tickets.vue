<template>
  <view class="cts">
    <!-- 状态 tabs：全部 / 待回复(1) / 已回复(2) / 已关闭(3) -->
    <view class="cts__tabs">
      <text
        v-for="t in TABS"
        :key="t.status"
        class="cts__tab"
        :class="{ 'cts__tab--active': activeStatus === t.status }"
        @tap="switchTab(t.status)"
      >
        {{ t.label }}
      </text>
    </view>

    <CSkeleton v-if="loading && !list.length" type="card" />
    <CError v-else-if="error && !list.length" @retry="() => loadPage(true)" />
    <CEmpty
      v-else-if="!list.length"
      icon="empty-chat"
      text="还没有问诊记录"
      button-text="去问诊"
      @action="goChat"
    />
    <template v-else>
      <view v-for="t in list" :key="t.id" class="t-card" @tap="openTicket(t)">
        <view class="t-card__head">
          <text class="t-card__title">{{ t.title || `问诊 #${t.id}` }}</text>
          <text class="t-card__status" :class="`t-card__status--${t.status}`">
            {{ STATUS_TEXT[t.status] || '未知' }}
          </text>
        </view>
        <view class="t-card__foot">
          <text class="t-card__time">提交于 {{ fmtTime(t.created_at) }}</text>
          <text class="t-card__arrow">›</text>
        </view>
      </view>

      <view v-if="loading" class="cts__more">加载中...</view>
      <view v-else-if="!hasMore" class="cts__more">没有更多了</view>
    </template>

    <!-- 新建问诊：直接进对话页（无工单时首条消息即建单） -->
    <view class="cts__fab" @tap="goChat">
      <image class="cts__fab-icon" src="/static/icons/ic-gym.png" mode="aspectFit" />
      <text class="cts__fab-text">发起问诊</text>
    </view>
  </view>
</template>

<script setup lang="ts">
/**
 * FE · 我的问诊工单列表 — G1
 * 契约：GET /api/coach/tickets（status/page/page_size，created_at DESC）
 * 点击 → /pages/coach/chat?id={id}（专家问诊对话页）
 */
import { ref } from 'vue'
import { onLoad, onReachBottom } from '@dcloudio/uni-app'
import { getCoachTickets } from '@/api/coach'
import type { CoachTicketItem } from '@/types/api'

/** tab status：undefined=全部（后端 status 可空） */
const TABS: { status: 1 | 2 | 3 | undefined; label: string }[] = [
  { status: undefined, label: '全部' },
  { status: 1, label: '待回复' },
  { status: 2, label: '已回复' },
  { status: 3, label: '已关闭' },
]

/** 工单状态文案（CoachTicketStatus） */
const STATUS_TEXT: Record<number, string> = { 1: '待教练回复', 2: '教练已回复', 3: '已关闭' }

const PAGE_SIZE = 10

const activeStatus = ref<1 | 2 | 3 | undefined>(undefined)
const list = ref<CoachTicketItem[]>([])
const page = ref(1)
const hasMore = ref(false)
const loading = ref(false)
const error = ref(false)

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
    const data = await getCoachTickets({
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

function openTicket(t: CoachTicketItem) {
  uni.navigateTo({ url: `/pages/coach/chat?id=${t.id}` })
}

function goChat() {
  uni.navigateTo({ url: '/pages/coach/chat' })
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
.cts {
  padding: $space-md;
  padding-bottom: calc(#{$space-xl} + 120rpx + env(safe-area-inset-bottom));

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

  &__fab {
    @include flex-center;

    position: fixed;
    right: $space-lg;
    bottom: calc(#{$space-lg} + env(safe-area-inset-bottom));
    z-index: $z-fab;
    height: 88rpx;
    padding: 0 $space-lg;
    background: $brand;
    border-radius: 999rpx;
    box-shadow: $shadow-lg;
  }

  &__fab-icon {
    width: 40rpx;
    height: 40rpx;
    margin-right: $space-xs;
  }

  &__fab-text {
    font-size: $t-26;
    font-weight: 500;
    color: var(--card);
  }
}

.t-card {
  padding: $space-lg;
  margin-bottom: $space-md;
  background: $card;
  border-radius: $radius;
  box-shadow: $shadow;

  &__head {
    @include flex-between;

    margin-bottom: $space-sm;
  }

  &__title {
    flex: 1;
    min-width: 0;
    font-size: $t-28;
    font-weight: 500;
    color: $text-1;
    @include ellipsis;
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

  &__foot {
    @include flex-between;
  }

  &__time {
    font-size: $t-22;
    color: $text-3;
  }

  &__arrow {
    font-size: $t-24;
    color: $text-3;
  }
}
</style>
