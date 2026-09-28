<template>
  <view class="c-state">
    <view class="c-state__icon">{{ icon }}</view>
    <text class="c-state__text">{{ text }}</text>
    <CButton v-if="buttonText" size="md" @click="emit('retry')">{{ buttonText }}</CButton>
  </view>
</template>

<script setup lang="ts">
import CButton from './CButton.vue'

interface Props {
  icon?: string
  /** 错误文案（§5.8：插画 + "网络开小差了" + 次按钮"重试"） */
  text?: string
  buttonText?: string
}

withDefaults(defineProps<Props>(), {
  icon: '⚠️',
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

  &__icon {
    @include flex-center;

    width: 120rpx;
    height: 120rpx;
    margin-bottom: $space-md;
    border-radius: 50%;
    background: #f3f4f6;
    font-size: 64rpx;
  }

  &__text {
    margin-bottom: $space-lg;
    font-size: $t-26;
    color: $text-2;
  }
}
</style>
