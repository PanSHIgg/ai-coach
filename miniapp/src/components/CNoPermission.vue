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
  /** 未登录插画资产名，渲染 /static/illustrations/{icon}.png */
  icon?: string
  /** 未登录/无权限文案（§5.8：插画 + "登录后查看" + 主按钮"去登录"） */
  text?: string
  buttonText?: string
}

withDefaults(defineProps<Props>(), {
  icon: 'empty-lock',
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
