<template>
  <view class="c-input" :class="{ 'c-input--focus': focused, 'c-input--disabled': disabled }">
    <input
      class="c-input__inner"
      :value="modelValue"
      :type="type"
      :placeholder="placeholder"
      placeholder-style="color: #9CA3AF"
      :disabled="disabled"
      :maxlength="maxlength"
      @input="onInput"
      @focus="onFocus"
      @blur="onBlur"
      @confirm="onConfirm"
    />
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'

interface Props {
  /** v-model 值 */
  modelValue?: string
  placeholder?: string
  /** uni input 原生类型（§4.7 输入框高 88rpx） */
  type?: 'text' | 'number' | 'digit' | 'idcard'
  disabled?: boolean
  maxlength?: number
}

withDefaults(defineProps<Props>(), {
  modelValue: '',
  placeholder: '',
  type: 'text',
  disabled: false,
  maxlength: 140,
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
  (e: 'focus', ev: Event): void
  (e: 'blur', ev: Event): void
  (e: 'confirm', ev: Event): void
}>()

const focused = ref(false)

function onInput(e: { detail: { value: string } }) {
  emit('update:modelValue', e.detail.value)
}
function onFocus(ev: Event) {
  focused.value = true
  emit('focus', ev)
}
function onBlur(ev: Event) {
  focused.value = false
  emit('blur', ev)
}
function onConfirm(ev: Event) {
  emit('confirm', ev)
}
</script>

<style lang="scss" scoped>
.c-input {
  display: flex;
  align-items: center;
  height: 88rpx;
  padding: 0 $space-md;
  background: $card;
  border: 1rpx solid $border;
  border-radius: $radius;
  transition: border-color $duration-fast linear;

  // 聚焦边框变 --brand（§4.7）
  &--focus {
    border-color: $brand;
  }

  // 【假设】禁用态底色文档未定义，取灰阶 #F9FAFB
  &--disabled {
    background: #f9fafb;
  }

  &__inner {
    flex: 1;
    width: 100%;
    height: 100%;
    font-size: $t-26;
    color: $text-1;
  }
}
</style>
