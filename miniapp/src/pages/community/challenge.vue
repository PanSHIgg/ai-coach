<template>
  <view class="ch">
    <CSkeleton v-if="loading && !loaded" type="card" />
    <CError v-else-if="error" @retry="load" />
    <template v-else>
      <CEmpty v-if="!challenges.length" icon="empty-crown" text="暂无挑战赛" button-text="" />
      <CCard v-for="c in challenges" :key="c.id" class="ch__card">
        <text class="ch__name">{{ c.title }}</text>
        <text class="ch__meta">参与 {{ c.join_count }} 人 · {{ c.status === 2 ? '已结束' : '进行中' }}</text>
        <view class="ch__actions">
          <CButton size="sm" :disabled="c.joined || c.status === 2" @click="join(c)">
            {{ c.joined ? '已参加' : '参加' }}
          </CButton>
          <CButton size="sm" type="secondary" @click="showBoard(c)">查看排行榜</CButton>
        </view>
        <view v-if="boards[c.id]" class="ch__board">
          <CEmpty v-if="!boards[c.id].length" icon="empty-crown" text="暂无排名" button-text="" />
          <view v-for="e in boards[c.id]" :key="e.user.id" class="ch__row">
            <text class="ch__rank">{{ e.rank }}</text>
            <text class="ch__nick">{{ e.user.nickname }}</text>
            <text class="ch__score">{{ e.score.toFixed(0) }} 分</text>
          </view>
        </view>
      </CCard>
    </template>
  </view>
</template>

<script setup lang="ts">
/**
 * FE5 · 挑战赛 — Phase 4 (M4)
 * 契约：GET /api/community/challenge/list、POST .../{id}/join、GET .../{id}/leaderboard
 */
import { reactive, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'

import { challengeLeaderboard, joinChallenge, listChallenges } from '@/api/community'
import type { ChallengeItem, LeaderboardEntry } from '@/types/api'
import { useToast } from '@/composables/useToast'

const toast = useToast()
const loading = ref(true)
const loaded = ref(false)
const error = ref(false)
const challenges = ref<ChallengeItem[]>([])
const boards = reactive<Record<number, LeaderboardEntry[]>>({})

async function load() {
  loading.value = true
  error.value = false
  try {
    challenges.value = (await listChallenges({ page_size: 50 })).items
  } catch {
    error.value = true
  } finally {
    loading.value = false
    loaded.value = true
  }
}

async function join(c: ChallengeItem) {
  try {
    const res = await joinChallenge(c.id)
    c.joined = true
    c.join_count = res.join_count
    toast.success({ title: '已参加挑战赛' })
  } catch {
    // request 层已 toast；失败不改本地态
  }
}

async function showBoard(c: ChallengeItem) {
  if (boards[c.id]) {
    delete boards[c.id]
    return
  }
  try {
    const res = await challengeLeaderboard(c.id)
    boards[c.id] = res.items
  } catch {
    // request 层已 toast；失败保持收起态
  }
}

onShow(() => {
  void load()
})
</script>

<style lang="scss" scoped>
.ch {
  padding: $space-md;

  &__card {
    margin-bottom: $space-md;
  }

  &__name {
    display: block;
    font-size: $t-28;
    font-weight: 600;
    color: $text-1;
  }

  &__meta {
    display: block;
    margin-top: $space-xs;
    font-size: $t-24;
    color: $text-2;
  }

  &__actions {
    display: flex;
    gap: $space-md;
    margin-top: $space-md;
  }

  &__board {
    margin-top: $space-md;
  }

  &__row {
    @include flex-between;

    padding: $space-xs 0;
    border-top: 1rpx solid $border;
  }

  &__rank {
    width: 48rpx;
    font-weight: 700;
    color: $brand;
  }

  &__nick {
    flex: 1;
    font-size: $t-26;
    color: $text-1;
  }

  &__score {
    font-size: $t-24;
    color: $text-2;
  }
}
</style>
