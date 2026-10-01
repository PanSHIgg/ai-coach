<template>
  <view class="c-state">
    <image class="c-state__illus" :src="`/static/illustrations/${icon}.png`" mode="aspectFit" />
    <text class="c-state__text">{{ text }}</text>
    <CButton v-if="buttonText" size="md" @click="emit('action')">{{ buttonText }}</CButton>
  </view>
</template>

<script setup lang="ts">
import CButton from './CButton.vue'

interface Props {
  /** 空态插画资产名，渲染 /static/illustrations/{icon}.png（§4.5 空状态插画） */
  icon?: string
  /** 空态文案（§5.8：插画 + "还没有记录" + 主按钮"去记录"） */
  text?: string
  /** 主按钮文案，传空串隐藏按钮 */
  buttonText?: string
}

withDefaults(defineProps<Props>(), {
  icon: 'empty-food',
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
