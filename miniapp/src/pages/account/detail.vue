<template>
  <view class="page-shell">
    <!-- 今日概览 -->
    <CCard title="今日概览" class="detail__card">
      <CSkeleton v-if="accountStore.loading && !accountStore.today" type="card" />
      <template v-else-if="accountStore.today">
        <view class="detail__row">
          <text class="detail__label">热量预算 TEE</text>
          <text class="detail__value">{{ tee }} kcal</text>
        </view>
        <view class="detail__row">
          <text class="detail__label">已摄入</text>
          <text class="detail__value">{{ intake }} kcal</text>
        </view>
        <view class="detail__row">
          <text class="detail__label">运动消耗</text>
          <text class="detail__value">{{ burnt }} kcal</text>
        </view>
        <view class="detail__row">
          <text class="detail__label">步数</text>
          <text class="detail__value">{{ steps }}</text>
        </view>
        <view class="detail__row">
          <text class="detail__label">今日缺口</text>
          <text class="detail__value" :class="{ 'detail__value--danger': deficit < 0 }">{{ deficit }} kcal</text>
        </view>
      </template>
      <CError v-else @retry="reload" />
    </CCard>

    <!-- 趋势占位（P1 接入 account/trend 曲线） -->
    <CCard title="趋势" class="detail__card">
      <CEmpty text="趋势图 P1 接入" button-text="敬请期待" @action="onTrend" />
    </CCard>
  </view>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { useAccountStore } from '@/stores/account'
import { useToast } from '@/composables/useToast'

const accountStore = useAccountStore()
const toast = useToast()

const tee = computed(() => Math.round(accountStore.today?.tee ?? 0))
const intake = computed(() => Math.round(accountStore.today?.intake ?? 0))
const burnt = computed(() => Math.round(accountStore.today?.calories_burnt ?? 0))
const steps = computed(() => (accountStore.today?.steps ?? 0).toLocaleString())
const deficit = computed(() => Math.round(accountStore.today?.deficit ?? 0))

onShow(() => {
  if (!accountStore.today) reload()
})

function reload() {
  accountStore.fetchToday()
}

function onTrend() {
  toast.info({ title: '趋势图 P1 接入' })
}
</script>

<style lang="scss" scoped>
.page-shell {
  padding: $space-md;
}

.detail {
  &__card {
    margin-bottom: $space-md;
  }

  &__row {
    @include flex-between;

    padding: $space-xs 0;
  }

  &__label {
    font-size: $t-26;
    color: $text-2;
  }

  &__value {
    font-size: $t-26;
    font-weight: 500;
    color: $text-1;

    &--danger {
      color: $danger;
    }
  }
}
</style>
