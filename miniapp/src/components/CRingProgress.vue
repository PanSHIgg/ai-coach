<template>
  <view class="c-ring" :style="ringStyle">
    <view class="c-ring__hole" :style="holeStyle" />
    <view class="c-ring__content">
      <slot />
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed } from 'vue'

interface Props {
  /** 进度 0-100（<0 按 0，>100 按 100 处理） */
  percent: number
  /** 直径 rpx */
  size?: number
  /** 环宽 rpx */
  strokeWidth?: number
  /** 进度色（健康区间：<60 --health-bad / 60-80 --health-mid / >80 --health-good，§4.12） */
  color?: string
  /** 轨道底色 */
  trackColor?: string
  /** 中心挖空底色（默认卡片白） */
  holeColor?: string
}

const props = withDefaults(defineProps<Props>(), {
  size: 240,
  strokeWidth: 24,
  // 默认值取 $brand / $border / $card 对应色值（script 内无法引用 SCSS 变量）
  color: '#22C55E',
  trackColor: '#E5E7EB',
  holeColor: '#FFFFFF',
})

const clamped = computed(() => Math.min(100, Math.max(0, props.percent)))

const ringStyle = computed(() => ({
  width: `${props.size}rpx`,
  height: `${props.size}rpx`,
  background: `conic-gradient(${props.color} ${clamped.value}%, ${props.trackColor} 0)`,
}))

const holeStyle = computed(() => ({
  top: `${props.strokeWidth}rpx`,
  right: `${props.strokeWidth}rpx`,
  bottom: `${props.strokeWidth}rpx`,
  left: `${props.strokeWidth}rpx`,
  background: props.holeColor,
}))
</script>

<style lang="scss" scoped>
.c-ring {
  position: relative;
  border-radius: 50%;

  &__hole {
    position: absolute;
    border-radius: 50%;
  }

  &__content {
    position: absolute;
    top: 0;
    right: 0;
    bottom: 0;
    left: 0;
    @include flex-center;
  }
}
</style>
