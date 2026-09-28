<template>
  <view class="c-card" :class="{ 'c-card--flush': !padding }">
    <view v-if="title || $slots.title" class="c-card__header">
      <slot name="title">
        <text class="c-card__title">{{ title }}</text>
      </slot>
      <!-- 标题行右侧操作区（§4.11：第一行标题左 + 可选操作右） -->
      <slot name="extra" />
    </view>
    <slot />
  </view>
</template>

<script setup lang="ts">
interface Props {
  /** 卡片标题（优先用 #title 插槽自定义） */
  title?: string
  /** 是否内边距 lg（§4.11 卡片内边距 lg=32rpx），flush 用于贴边内容 */
  padding?: boolean
}

withDefaults(defineProps<Props>(), {
  title: '',
  padding: true,
})
</script>

<style lang="scss" scoped>
.c-card {
  background: $card;
  border-radius: $radius;
  box-shadow: $shadow;
  padding: $space-lg;

  &--flush {
    padding: 0;
    overflow: hidden;
  }

  &__header {
    @include flex-between;

    margin-bottom: $space-sm;
  }

  &__title {
    font-size: $t-28;
    font-weight: 500;
    color: $text-1;
  }
}
</style>
