<template>
  <view class="sv">
    <CSkeleton v-if="loading" type="card" />
    <CError v-else-if="error" @retry="load" />
    <template v-else>
      <CCard v-if="supervise" class="sv__card">
        <text class="sv__title">👥 我的监督搭子</text>
        <text class="sv__desc">{{ supervise.partner.nickname }} · 已互相监督 {{ supervise.days }} 天</text>
        <view class="sv__actions">
          <CButton size="sm" type="secondary" @click="remind">提醒打卡</CButton>
          <CButton size="sm" @click="toggleRecords">{{ showRecords ? '收起记录' : '查看她的记录' }}</CButton>
        </view>
      </CCard>
      <CCard v-else class="sv__card">
        <text class="sv__title">👥 还没有监督搭子</text>
        <text class="sv__desc">匹配一个减友，互相监督打卡</text>
        <CButton class="sv__match" :loading="matching" @click="match">匹配搭子</CButton>
      </CCard>

      <CCard v-if="showRecords && records" class="sv__card">
        <text class="sv__title">{{ records.partner.nickname }} 的近 7 天</text>
        <CEmpty v-if="!records.items.length" icon="📈" text="暂无记录" button-text="" />
        <view v-for="r in records.items" :key="r.date" class="sv__rec">
          <text class="sv__rec-date">{{ r.date }}</text>
          <text class="sv__rec-val">摄入 {{ r.intake.toFixed(0) }} · 步数 {{ r.steps }} · 缺口 {{ r.deficit.toFixed(0) }}</text>
        </view>
      </CCard>
    </template>
  </view>
</template>

<script setup lang="ts">
/**
 * FE5 · 监督搭子 — Phase 4 (M4)
 * 契约：GET /api/community/supervise、POST .../match、.../{id}/remind、.../{id}/records
 */
import { ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'

import { getSupervise, matchSupervise, remindSupervise, superviseRecords } from '@/api/community'
import type { SuperviseOut, SuperviseRecordsData } from '@/types/api'
import { useToast } from '@/composables/useToast'

const toast = useToast()
const loading = ref(true)
const error = ref(false)
const supervise = ref<SuperviseOut | null>(null)
const records = ref<SuperviseRecordsData | null>(null)
const showRecords = ref(false)
const matching = ref(false)

async function load() {
  loading.value = true
  error.value = false
  try {
    supervise.value = await getSupervise()
  } catch {
    supervise.value = null // 3001：尚无搭子
  } finally {
    loading.value = false
  }
}

async function match() {
  matching.value = true
  try {
    supervise.value = await matchSupervise({})
    toast.success({ title: '匹配成功' })
  } catch {
    // request 层已 toast
  } finally {
    matching.value = false
  }
}

async function remind() {
  if (!supervise.value) return
  try {
    const res = await remindSupervise(supervise.value.id)
    toast.info({ title: res.message })
  } catch {
    // request 层已 toast
  }
}

async function toggleRecords() {
  if (!supervise.value) return
  showRecords.value = !showRecords.value
  if (showRecords.value && !records.value) {
    try {
      records.value = await superviseRecords(supervise.value.id)
    } catch {
      // request 层已 toast；失败保持无记录态
    }
  }
}

onShow(() => {
  void load()
})
</script>

<style lang="scss" scoped>
.sv {
  padding: $space-md;

  &__card {
    margin-bottom: $space-md;
  }

  &__title {
    display: block;
    font-size: $t-28;
    font-weight: 600;
    color: $text-1;
  }

  &__desc {
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

  &__match {
    margin-top: $space-md;
  }

  &__rec {
    padding: $space-sm 0;
    border-top: 1rpx solid $border;
  }

  &__rec-date {
    display: block;
    font-size: $t-24;
    color: $text-1;
  }

  &__rec-val {
    display: block;
    font-size: $t-22;
    color: $text-3;
  }
}
</style>
