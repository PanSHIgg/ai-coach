<template>
  <view class="c-nobenefit">
    <!-- 灰显内容预览（§5.8：页面内容灰显预览 + 浮层"该功能需进阶版"） -->
    <view class="c-nobenefit__preview">
      <slot />
    </view>
    <view class="c-nobenefit__mask">
      <view class="c-nobenefit__panel">
        <text class="c-nobenefit__text">{{ text }}</text>
        <CButton size="sm" @click="emit('action')">{{ buttonText }}</CButton>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import CButton from './CButton.vue'

interface Props {
  /** 浮层文案 */
  text?: string
  buttonText?: string
}

withDefaults(defineProps<Props>(), {
  text: '该功能需进阶版',
  buttonText: '立即开通',
})

const emit = defineEmits<{
  (e: 'action'): void
}>()
</script>

<style lang="scss" scoped>
.c-nobenefit {
  position: relative;
  min-height: 240rpx;

  &__preview {
    filter: grayscale(1);
    opacity: 0.4;
    // H5 生效；小程序端点击由下方 mask 全覆盖天然拦截
    pointer-events: none;
  }

  &__mask {
    position: absolute;
    top: 0;
    right: 0;
    bottom: 0;
    left: 0;
    z-index: $z-mask;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  &__panel {
    @include flex-center(column);

    padding: $space-lg;
    background: $card;
    border-radius: $radius;
    box-shadow: $shadow-lg;
  }

  &__text {
    margin-bottom: $space-md;
    font-size: $t-26;
    color: $text-2;
  }
}
</style>
