<template>
  <view
    class="c-btn"
    :class="[`c-btn--${type}`, `c-btn--${size}`, { 'c-btn--block': block, 'c-btn--disabled': disabled || loading }]"
    @tap="handleTap"
  >
    <view v-if="loading" class="c-btn__spinner" />
    <slot />
  </view>
</template>

<script setup lang="ts">
interface Props {
  /** 按钮类型：primary 主操作 / secondary 次操作 / ghost 文字按钮 / danger 删除等危险操作（§4.6） */
  type?: 'primary' | 'secondary' | 'ghost' | 'danger'
  /** 尺寸：lg 主按钮高 88rpx（§4.6） / md / sm 【假设】md/sm 文档未定义，按 4 点栅格推导 */
  size?: 'lg' | 'md' | 'sm'
  loading?: boolean
  disabled?: boolean
  /** 是否通栏（全宽） */
  block?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  type: 'primary',
  size: 'lg',
  loading: false,
  disabled: false,
  block: false,
})

const emit = defineEmits<{
  (e: 'click', ev: Event): void
}>()

function handleTap(ev: Event) {
  if (props.disabled || props.loading) return
  emit('click', ev)
}
</script>

<style lang="scss" scoped>
.c-btn {
  @include flex-center;
  @include press;

  border-radius: $radius;
  font-weight: 500;

  &--lg {
    height: 88rpx;
    padding: 0 $space-lg;
    font-size: $t-28;
  }

  &--md {
    height: 72rpx;
    padding: 0 $space-md;
    font-size: $t-26;
  }

  &--sm {
    height: 56rpx;
    padding: 0 $space-sm;
    font-size: $t-24;
    border-radius: $radius-sm;
  }

  &--block {
    width: 100%;
  }

  &--primary {
    background: $brand;
    color: var(--card);
  }

  &--secondary {
    background: $card;
    color: $brand;
    border: 1rpx solid $border;
  }

  &--ghost {
    background: transparent;
    color: $brand;
  }

  &--danger {
    background: $danger;
    color: var(--card);
  }

  // 禁用（§4.6：底 #D1D5DB、字白、不可点）；置于类型类之后保证覆盖
  &--disabled {
    background: $disabled;
    color: var(--card);
    border-color: transparent;
  }

  &__spinner {
    // 用 SCSS 令牌 $card：此处不能写 CSS 变量形式，mixin 内部会做
    // rgba($color, .3)，而 CSS rgba() 不接受 var() 解析出的 hex，会整条声明失效。
    @include spin(28rpx, 3rpx, $card);

    margin-right: $space-xs;
  }
}
</style>
