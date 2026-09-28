<template>
  <view class="c-field">
    <view v-if="label" class="c-field__label">
      <text v-if="required" class="c-field__required">*</text>
      <text>{{ label }}</text>
    </view>
    <slot />
    <text v-if="error" class="c-field__error">{{ error }}</text>
    <text v-else-if="hint" class="c-field__hint">{{ hint }}</text>
  </view>
</template>

<script setup lang="ts">
interface Props {
  /** 标签在上（§4.7） */
  label?: string
  /** 必填标记（红星） */
  required?: boolean
  /** 错误提示（红字，优先于 hint） */
  error?: string
  /** 辅助说明 */
  hint?: string
}

withDefaults(defineProps<Props>(), {
  label: '',
  required: false,
  error: '',
  hint: '',
})
</script>

<style lang="scss" scoped>
.c-field {
  margin-bottom: $space-md;

  &__label {
    font-size: $t-26;
    color: $text-2;
    margin-bottom: $space-xs;
  }

  &__required {
    color: $danger;
    margin-right: 4rpx;
  }

  &__error {
    display: block;
    font-size: $t-22;
    color: $danger;
    margin-top: $space-xs;
  }

  &__hint {
    display: block;
    font-size: $t-22;
    color: $text-3;
    margin-top: $space-xs;
  }
}
</style>
