<template>
  <view class="community">
    <!-- Tab：榜单/监督/兴趣社群/约战/挑战赛/动态 -->
    <scroll-view class="community__tabs" scroll-x>
      <text
        v-for="t in TABS"
        :key="t.key"
        class="community__tab"
        :class="{ 'community__tab--active': active === t.key }"
        @tap="switchTab(t.key)"
      >
        {{ t.label }}
      </text>
    </scroll-view>

    <CSkeleton v-if="loading && !loaded" type="card" />
    <CError v-else-if="error" @retry="reload" />

    <!-- 1. 热量控制榜 -->
    <view v-else-if="active === 'rank'" class="community__panel">
      <CCard class="community__card">
        <view class="community__row community__row--head">
          <text class="community__title">热量控制榜 · 本周</text>
          <text class="community__link" @tap="reload">刷新</text>
        </view>
        <view v-for="it in leaderboard" :key="it.user.id" class="rank-row">
          <text class="rank-row__no" :class="{ 'rank-row__no--top': it.rank <= 3 }">{{ it.rank }}</text>
          <text class="rank-row__name">{{ it.user.nickname }}</text>
          <text class="rank-row__score">{{ it.score.toFixed(0) }}</text>
        </view>
        <CEmpty v-if="!leaderboard.length" icon="🏆" text="暂无榜单数据" button-text="" />
      </CCard>
    </view>

    <!-- 2. 监督 -->
    <view v-else-if="active === 'supervise'" class="community__panel">
      <CCard class="community__card">
        <view class="community__row community__row--head">
          <text class="community__title">👥 我的监督</text>
          <text class="community__link" @tap="go('/pages/community/supervise')">查看</text>
        </view>
        <template v-if="supervise">
          <text class="community__desc">
            {{ supervise.partner.nickname }} · 已互相监督 {{ supervise.days }} 天
          </text>
        </template>
        <text v-else class="community__desc">还没有监督搭子，去匹配一个吧</text>
      </CCard>
    </view>

    <!-- 3. 兴趣社群 -->
    <view v-else-if="active === 'group'" class="community__panel">
      <CCard class="community__card">
        <view class="community__row community__row--head">
          <text class="community__title">🏃 兴趣社群</text>
          <text class="community__link" @tap="go('/pages/community/group')">全部</text>
        </view>
        <view v-for="g in groups.slice(0, 3)" :key="g.id" class="community__line" @tap="go('/pages/community/group')">
          <text class="community__line-title">{{ g.name }}</text>
          <text class="community__desc">{{ g.member_count }}人</text>
        </view>
        <CEmpty v-if="!groups.length" icon="🏃" text="暂无社群" button-text="" />
      </CCard>
    </view>

    <!-- 4. 约战 -->
    <view v-else-if="active === 'battle'" class="community__panel">
      <CCard class="community__card">
        <view class="community__row community__row--head">
          <text class="community__title">🏸 约战</text>
          <text class="community__link" @tap="go('/pages/community/battle')">全部 / 发起</text>
        </view>
        <view v-for="b in battles.slice(0, 3)" :key="b.id" class="community__line">
          <text class="community__line-title">{{ b.title }}</text>
          <text class="community__desc">
            {{ b.sport_name || '运动' }} · 缺 {{ Math.max(b.need_count - b.join_count, 0) }} 人
          </text>
        </view>
        <CEmpty v-if="!battles.length" icon="🏸" text="暂无约战" button-text="" />
      </CCard>
    </view>

    <!-- 5. 挑战赛 -->
    <view v-else-if="active === 'challenge'" class="community__panel">
      <CCard class="community__card">
        <view class="community__row community__row--head">
          <text class="community__title">🔥 挑战赛</text>
          <text class="community__link" @tap="go('/pages/community/challenge')">全部</text>
        </view>
        <view v-for="c in challenges.slice(0, 3)" :key="c.id" class="community__line">
          <text class="community__line-title">{{ c.title }}</text>
          <text class="community__desc">参与 {{ c.join_count }} 人 · {{ c.joined ? '已参加' : '未参加' }}</text>
        </view>
        <CEmpty v-if="!challenges.length" icon="🔥" text="暂无挑战赛" button-text="" />
      </CCard>
    </view>

    <!-- 6. 动态 -->
    <view v-else class="community__panel">
      <view v-for="p in posts" :key="p.id" class="post-card" @tap="goPost(p.id)">
        <view class="post-card__head">
          <text class="post-card__name">{{ p.user.nickname }}</text>
          <text class="post-card__time">{{ fmtTime(p.created_at) }}</text>
        </view>
        <text class="post-card__content">{{ p.content }}</text>
        <view class="post-card__foot">
          <text class="post-card__action" @tap.stop="toggleLike(p)">
            {{ p.liked ? '❤️' : '🤍' }} {{ p.like_count }}
          </text>
          <text class="post-card__action">💬 {{ p.comment_count }}</text>
        </view>
      </view>
      <CEmpty v-if="!posts.length" icon="💬" text="还没有动态，发一条吧" button-text="发动态" @action="goPost(0)" />
    </view>

    <CButton v-if="active === 'post'" class="community__fab" size="md" @click="goPost(0)">
      ＋ 发动态
    </CButton>
  </view>
</template>

<script setup lang="ts">
/**
 * FE5 · 社区 — Phase 4 (M4)
 * 依据：docs/split/03-页面布局与交互说明.md §5.4 社区（五种社交）
 * 契约：/api/community/{leaderboard,supervise,group/list,battle/list,challenge/list,post/list}
 * 【假设】动态发帖/详情/评论复用 pages/community/post（无 id=发帖，带 id=详情）。
 */
import { ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'

import {
  getLeaderboard,
  getSupervise,
  likePost,
  listBattles,
  listChallenges,
  listGroups,
  listPosts,
  unlikePost,
} from '@/api/community'
import type {
  BattleItem,
  ChallengeItem,
  CommunityPostOut,
  GroupItem,
  LeaderboardEntry,
  SuperviseOut,
} from '@/types/api'

const TABS = [
  { key: 'rank', label: '榜单' },
  { key: 'supervise', label: '监督' },
  { key: 'group', label: '兴趣社群' },
  { key: 'battle', label: '约战' },
  { key: 'challenge', label: '挑战赛' },
  { key: 'post', label: '动态' },
] as const

type TabKey = (typeof TABS)[number]['key']

const active = ref<TabKey>('rank')
const loading = ref(true)
const loaded = ref(false)
const error = ref(false)

const leaderboard = ref<LeaderboardEntry[]>([])
const supervise = ref<SuperviseOut | null>(null)
const groups = ref<GroupItem[]>([])
const battles = ref<BattleItem[]>([])
const challenges = ref<ChallengeItem[]>([])
const posts = ref<CommunityPostOut[]>([])

function go(url: string) {
  uni.navigateTo({ url })
}

function goPost(id: number) {
  uni.navigateTo({ url: id ? `/pages/community/post?id=${id}` : '/pages/community/post' })
}

function fmtTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return `${d.getMonth() + 1}-${String(d.getDate()).padStart(2, '0')}`
}

async function reload() {
  loading.value = true
  error.value = false
  try {
    const [rank, sup, gs, bs, cs, ps] = await Promise.all([
      getLeaderboard({ period_type: 2 }).catch(() => null),
      getSupervise().catch(() => null),
      listGroups({ page_size: 20 }).catch(() => null),
      listBattles({ page_size: 20 }).catch(() => null),
      listChallenges({ page_size: 20 }).catch(() => null),
      listPosts({ page_size: 20 }).catch(() => null),
    ])
    leaderboard.value = rank?.items ?? []
    supervise.value = sup
    groups.value = gs?.items ?? []
    battles.value = bs?.items ?? []
    challenges.value = cs?.items ?? []
    posts.value = ps?.items ?? []
  } catch {
    error.value = true
  } finally {
    loading.value = false
    loaded.value = true
  }
}

async function toggleLike(p: CommunityPostOut) {
  try {
    const res = p.liked ? await unlikePost(p.id) : await likePost(p.id)
    p.liked = res.liked
    p.like_count = res.like_count
  } catch {
    // request 层已 toast；失败不改本地态，避免点赞数错乱
  }
}

function switchTab(key: TabKey) {
  active.value = key
}

onShow(() => {
  void reload()
})
</script>

<style lang="scss" scoped>
.community {
  padding: $space-md;
  padding-bottom: calc(#{$space-xl} + env(safe-area-inset-bottom));

  &__tabs {
    display: flex;
    white-space: nowrap;
    margin-bottom: $space-md;
  }

  &__tab {
    display: inline-block;
    padding: $space-sm $space-md;
    margin-right: $space-xs;
    font-size: $t-24;
    color: $text-2;
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

  &__card {
    margin-bottom: $space-md;
  }

  &__row {
    @include flex-between;

    &--head {
      margin-bottom: $space-sm;
    }
  }

  &__title {
    font-size: $t-28;
    font-weight: 600;
    color: $text-1;
  }

  &__link {
    font-size: $t-24;
    color: $brand;
  }

  &__desc {
    display: block;
    font-size: $t-24;
    color: $text-2;
  }

  &__line {
    padding: $space-sm 0;
    border-top: 1rpx solid $border;

    &-title {
      display: block;
      font-size: $t-26;
      color: $text-1;
    }
  }
}

.rank-row {
  @include flex-between;

  padding: $space-sm 0;
  border-top: 1rpx solid $border;

  &__no {
    width: 48rpx;
    font-weight: 700;
    color: $text-3;

    &--top {
      color: $brand;
    }
  }

  &__name {
    flex: 1;
    font-size: $t-26;
    color: $text-1;
  }

  &__score {
    font-size: $t-26;
    color: $text-2;
  }
}

.post-card {
  padding: $space-md;
  margin-bottom: $space-md;
  background: $card;
  border-radius: $radius;
  box-shadow: $shadow;

  &__head {
    @include flex-between;

    margin-bottom: $space-xs;
  }

  &__name {
    font-size: $t-26;
    font-weight: 500;
    color: $text-1;
  }

  &__time {
    font-size: $t-22;
    color: $text-3;
  }

  &__content {
    display: block;
    font-size: $t-26;
    color: $text-1;
  }

  &__foot {
    display: flex;
    gap: $space-lg;
    margin-top: $space-sm;
  }

  &__action {
    font-size: $t-24;
    color: $text-2;
  }
}

.community__fab {
  margin-top: $space-md;
}
</style>
