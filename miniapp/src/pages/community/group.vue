<template>
  <view class="grp">
    <CSkeleton v-if="loading && !loaded" type="card" />
    <CError v-else-if="error" @retry="load" />
    <template v-else>
      <CEmpty v-if="!groups.length" icon="empty-sport" text="暂无社群" button-text="" />
      <CCard v-for="g in groups" :key="g.id" class="grp__card">
        <text class="grp__name">{{ g.name }}</text>
        <text class="grp__meta">{{ g.category || '兴趣' }} · {{ g.member_count }}人 · {{ g.city || '全国' }}</text>
        <view class="grp__actions">
          <CButton size="sm" type="secondary" @click="join(g)">加入社群</CButton>
          <CButton size="sm" @click="checkin(g)">今日打卡</CButton>
        </view>
      </CCard>
    </template>
  </view>
</template>

<script setup lang="ts">
/**
 * FE5 · 兴趣社群 — Phase 4 (M4)
 * 契约：GET /api/community/group/list、POST .../{id}/join、POST .../{id}/checkin
 */
import { ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'

import { checkinGroup, joinGroup, listGroups } from '@/api/community'
import type { GroupItem } from '@/types/api'
import { useToast } from '@/composables/useToast'

const toast = useToast()
const loading = ref(true)
const loaded = ref(false)
const error = ref(false)
const groups = ref<GroupItem[]>([])
/** 加入/打卡进行中：防止连点重复请求 */
const busy = ref(false)

async function load() {
  loading.value = true
  error.value = false
  try {
    groups.value = (await listGroups({ page_size: 50 })).items
  } catch {
    error.value = true
  } finally {
    loading.value = false
    loaded.value = true
  }
}

async function join(g: GroupItem) {
  if (busy.value) return
  busy.value = true
  try {
    const res = await joinGroup(g.id)
    g.member_count = res.member_count
    toast.success({ title: '已加入社群' })
  } catch {
    // request 层已 toast；失败不改本地态
  } finally {
    busy.value = false
  }
}

async function checkin(g: GroupItem) {
  if (busy.value) return
  busy.value = true
  try {
    const res = await checkinGroup(g.id)
    toast.success({ title: `打卡成功，累计 ${res.checkin_days} 天` })
  } catch {
    // request 层已 toast
  } finally {
    busy.value = false
  }
}

onShow(() => {
  void load()
})
</script>

<style lang="scss" scoped>
.grp {
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
}
</style>
