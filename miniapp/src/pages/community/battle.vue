<template>
  <view class="bt">
    <view class="bt__head">
      <text class="bt__title">约战</text>
      <text class="bt__link" @tap="showCreate = !showCreate">{{ showCreate ? '收起' : '发起约战' }}</text>
    </view>

    <!-- 发起约战 -->
    <CCard v-if="showCreate" class="bt__card">
      <input v-model="form.title" class="bt__input" placeholder="约战标题" maxlength="256" />
      <input v-model="form.sport_name" class="bt__input" placeholder="运动类型（如 羽毛球）" maxlength="64" />
      <input v-model="form.city" class="bt__input" placeholder="城市（LBS 匹配）" maxlength="64" />
      <view class="bt__field">
        <text class="bt__label">需要人数</text>
        <input v-model="needStr" class="bt__input bt__input--mini" type="number" />
      </view>
      <CButton block :loading="creating" @click="create">发布约战</CButton>
    </CCard>

    <CSkeleton v-if="loading && !loaded" type="card" />
    <CError v-else-if="error" @retry="load" />
    <template v-else>
      <CEmpty v-if="!battles.length" icon="empty-sport" text="暂无约战" button-text="" />
      <CCard v-for="b in battles" :key="b.id" class="bt__card">
        <text class="bt__name">{{ b.title }}</text>
        <text class="bt__meta">
          {{ b.sport_name || '运动' }} · {{ b.city || '不限' }} · 已有 {{ b.join_count }}/{{ b.need_count }} 人
        </text>
        <CButton
          class="bt__join"
          size="sm"
          :disabled="b.status !== 1 || b.join_count >= b.need_count"
          @click="join(b)"
        >
          {{ b.status !== 1 || b.join_count >= b.need_count ? '已满员' : '加入' }}
        </CButton>
      </CCard>
    </template>
  </view>
</template>

<script setup lang="ts">
/**
 * FE5 · 约战 — Phase 4 (M4)
 * 契约：POST /api/community/battle、GET .../battle/list、POST .../battle/join（满员 2001）
 */
import { reactive, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'

import { createBattle, joinBattle, listBattles } from '@/api/community'
import type { BattleItem } from '@/types/api'
import { useToast } from '@/composables/useToast'

const toast = useToast()
const loading = ref(true)
const loaded = ref(false)
const error = ref(false)
const battles = ref<BattleItem[]>([])
const showCreate = ref(false)
const creating = ref(false)
const needStr = ref('2')
const form = reactive({ title: '', sport_name: '', city: '' })

async function load() {
  loading.value = true
  error.value = false
  try {
    battles.value = (await listBattles({ page_size: 50 })).items
  } catch {
    error.value = true
  } finally {
    loading.value = false
    loaded.value = true
  }
}

async function create() {
  if (!form.title.trim()) {
    toast.info({ title: '请输入标题' })
    return
  }
  creating.value = true
  try {
    const item = await createBattle({
      title: form.title.trim(),
      sport_name: form.sport_name.trim() || null,
      city: form.city.trim() || null,
      meet_at: new Date(Date.now() + 86400000).toISOString(),
      need_count: Number(needStr.value) || 2,
    })
    battles.value.unshift(item)
    showCreate.value = false
    form.title = ''
    form.sport_name = ''
    form.city = ''
    toast.success({ title: '已发起约战' })
  } catch {
    // request 层已 toast
  } finally {
    creating.value = false
  }
}

async function join(b: BattleItem) {
  try {
    const res = await joinBattle({ battle_id: b.id })
    b.join_count = res.join_count
    if (b.join_count >= b.need_count) b.status = 2
    toast.success({ title: '已加入约战' })
  } catch {
    // request 层已 toast（满员 2001 等）；失败不改本地态
  }
}

onShow(() => {
  void load()
})
</script>

<style lang="scss" scoped>
.bt {
  padding: $space-md;

  &__head {
    @include flex-between;

    margin-bottom: $space-md;
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

  &__card {
    margin-bottom: $space-md;
  }

  &__input {
    height: 72rpx;
    padding: 0 $space-sm;
    margin-bottom: $space-sm;
    font-size: $t-26;
    background: $bg;
    border-radius: $radius-sm;

    &--mini {
      flex: 1;
      margin-bottom: 0;
    }
  }

  &__field {
    display: flex;
    align-items: center;
    gap: $space-sm;
    margin-bottom: $space-sm;
  }

  &__label {
    font-size: $t-26;
    color: $text-1;
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

  &__join {
    margin-top: $space-md;
  }
}
</style>
