<template>
  <view class="bt">
    <view class="bt__head">
      <text class="bt__title">约战</text>
      <text class="bt__link" @tap="showCreate = !showCreate">{{ showCreate ? '收起' : '发起约战' }}</text>
    </view>

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
      <CEmpty v-if="!battles.length" icon="empty-battle" text="暂无约战" button-text="" />
      <CCard v-for="b in battles" :key="b.id" class="bt__card">
        <text class="bt__name">{{ b.title }}</text>
        <text class="bt__meta">
          {{ b.sport_name || '运动' }} · {{ b.city || '不限' }} · 已有 {{ b.join_count }}/{{ b.need_count }} 人
        </text>
        <view class="bt__actions">
          <CButton
            v-if="b.joined"
            size="sm"
            type="ghost"
            :disabled="b.status !== 1 && b.status !== 2"
            @click="quit(b)"
          >
            {{ b.status === 1 || b.status === 2 ? '退出约战' : '已开始' }}
          </CButton>
          <CButton
            v-else
            size="sm"
            :disabled="b.status !== 1 || b.join_count >= b.need_count"
            @click="join(b)"
          >
            {{ b.status !== 1 || b.join_count >= b.need_count ? '已满员' : '加入' }}
          </CButton>
          <text v-if="b.can_delete" class="bt__del" @tap="remove(b)">删除约战</text>
        </view>
      </CCard>
    </template>
  </view>
</template>

<script setup lang="ts">
/**
 * FE5 · 约战 — Phase 4 (M4)
 * 契约：POST /api/community/battle、GET .../battle/list、POST .../battle/join、
 *       POST .../battle/quit、DELETE .../battle/{id}
 * 一人一位（后端成员表防重复，重复加入 2001）；已加入可退出，满员退出后回「招募中」，
 * 退出后能再加入。joined / can_delete 一律取后端返回值，前端不自造成员态。
 */
import { reactive, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'

import { createBattle, deleteBattle, joinBattle, listBattles, quitBattle } from '@/api/community'
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

function confirm(content: string, title = '确认操作') {
  return new Promise<boolean>((resolve) => {
    uni.showModal({
      title,
      content,
      success: (res) => resolve(!!res.confirm),
      fail: () => resolve(false),
    })
  })
}

async function join(b: BattleItem) {
  // 防手抖双击：本地点位已在请求前置灰（:disabled 由 joined/满员推导），再兜一层
  if (b.joined) return
  try {
    const res = await joinBattle({ battle_id: b.id })
    b.join_count = res.join_count
    b.joined = true
    if (b.join_count >= b.need_count) b.status = 2
    toast.success({ title: '已加入约战' })
  } catch {
    // request 层已 toast（重复加入 2001 / 满员 2001 等）；失败后刷新拿到真实成员态
    void load()
  }
}

async function quit(b: BattleItem) {
  if (!(await confirm('确定退出这场约战吗？', '退出约战'))) return
  try {
    const res = await quitBattle({ battle_id: b.id })
    b.join_count = res.join_count
    b.joined = false
    // 满员退出后回「招募中」，其他人可以再加入
    if (b.status === 2 && b.join_count < b.need_count) b.status = 1
    toast.success({ title: '已退出约战' })
  } catch {
    // request 层已 toast（未加入 2001 等）；失败后刷新拿到真实成员态
    void load()
  }
}

async function remove(b: BattleItem) {
  if (!(await confirm('删除后其他已加入的人也会失去这场约战，确定删除吗？', '删除约战'))) return
  try {
    await deleteBattle(b.id)
    battles.value = battles.value.filter((x) => x.id !== b.id)
    toast.success({ title: '已删除约战' })
  } catch {
    void load()
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

  &__actions {
    display: flex;
    gap: $space-md;
    align-items: center;

    margin-top: $space-sm;
  }

  // 危险操作降权：文字链 + 靠右，避免与主 CTA 同权重误触
  &__del {
    margin-left: auto;

    font-size: $t-24;
    color: $danger;
  }
}
</style>
