<template>
  <view class="page-shell">
    <CSkeleton v-if="loading" type="card" />
    <CEmpty v-else text="附近商家正在入驻" @action="onAction" />
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { useToast } from '@/composables/useToast'

const toast = useToast()
const loading = ref(true)

// Tab 壳页：商家列表（P3 FE4 接入 LBS 比价）
onShow(() => {
  loading.value = true
  setTimeout(() => {
    loading.value = false
  }, 600)
})

function onAction() {
  toast.info({ title: '商家功能 P3 接入' })
}
</script>

<style lang="scss" scoped>
.page-shell {
  padding: $space-md;
}
</style>
