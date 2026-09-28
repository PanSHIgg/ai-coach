<template>
  <view class="c-state">
    <view class="c-state__icon">{{ icon }}</view>
    <text class="c-state__text">{{ text }}</text>
    <CButton v-if="buttonText" size="md" @click="emit('action')">{{ buttonText }}</CButton>
  </view>
</template>

<script setup lang="ts">
import CButton from './CButton.vue'

interface Props {
  icon?: string
  /** 未登录/无权限文案（§5.8：插画 + "登录后查看" + 主按钮"去登录"） */
  text?: string
  buttonText?: string
}

withDefaults(defineProps<Props>(), {
  icon: '🔒',
  text: '登录后查看',
  buttonText: '去登录',
})

const emit = defineEmits<{
  (e: 'action'): void
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
