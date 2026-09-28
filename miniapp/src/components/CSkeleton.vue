<template>
  <view class="c-skeleton">
    <!-- 卡片形态：标题条 + 3 行正文（§5.8 加载中用骨架屏） -->
    <template v-if="type === 'card'">
      <view class="c-skeleton__bar c-skeleton__bar--title" />
      <view
        v-for="i in 3"
        :key="i"
        class="c-skeleton__bar"
        :class="{ 'c-skeleton__bar--short': i === 3 }"
      />
    </template>
    <!-- 行形态：rows 行，末行 60% 宽 -->
    <template v-else>
      <view
        v-for="i in rows"
        :key="i"
        class="c-skeleton__bar"
        :class="{ 'c-skeleton__bar--short': i === rows }"
      />
    </template>
  </view>
</template>

<script setup lang="ts">
interface Props {
  /** line 行骨架 / card 卡片骨架 */
  type?: 'line' | 'card'
  /** line 形态行数 */
  rows?: number
}

withDefaults(defineProps<Props>(), {
  type: 'line',
  rows: 3,
})
</script>

<style lang="scss" scoped>
.c-skeleton {
  &__bar {
    height: 24rpx;
    margin-bottom: $space-sm;
    border-radius: $radius-sm;
    background: $border;
    animation: skeleton-pulse 1.2s ease-in-out infinite;

    &:last-child {
      margin-bottom: 0;
    }

    &--title {
      height: 32rpx;
      width: 40%;
    }

    &--short {
      width: 60%;
    }
  }
}
</style>
