<template>
  <view class="c-state">
    <image class="c-state__illus" :src="`/static/illustrations/${icon}.png`" mode="aspectFit" />
    <text class="c-state__text">{{ text }}</text>
    <CButton v-if="buttonText" size="md" @click="emit('retry')">{{ buttonText }}</CButton>
  </view>
</template>

<script setup lang="ts">
import CButton from './CButton.vue'

interface Props {
  /** 错误插画资产名，渲染 /static/illustrations/{icon}.png */
  icon?: string
  /** 错误文案（§5.8：插画 + "网络开小差了" + 次按钮"重试"） */
  text?: string
  buttonText?: string
}

withDefaults(defineProps<Props>(), {
  icon: 'empty-error',
  text: '网络开小差了',
  buttonText: '重试',
})

const emit = defineEmits<{
  (e: 'retry'): void
}>()
</script>

<style lang="scss" scoped>
.c-state {
  @include flex-center(column);

  padding: $space-xl $space-lg;

  &__illus {
    width: 176rpx;
    height: 176rpx;
    margin-bottom: $space-md;
  }

  &__text {
    margin-bottom: $space-lg;
    font-size: $t-26;
    color: $text-2;
  }
}
</style>
