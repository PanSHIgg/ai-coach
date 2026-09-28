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
  /** 图标占位（§4.5 空状态插画 64rpx；未引 uni-icons 依赖，用 emoji 占位可替换） */
  icon?: string
  /** 空态文案（§5.8：插画 + "还没有记录" + 主按钮"去记录"） */
  text?: string
  /** 主按钮文案，传空串隐藏按钮 */
  buttonText?: string
}

withDefaults(defineProps<Props>(), {
  icon: '🍽️',
  text: '还没有记录',
  buttonText: '去记录',
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
    // 【假设】插画底色文档未定义，取灰阶 #F3F4F6
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
