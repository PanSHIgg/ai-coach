<template>
  <view class="page-shell">
    <CSkeleton v-if="loading" type="card" />
    <CEmpty v-else text="还没有饮食记录，去记录第一餐吧" @action="onAction" />
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { useToast } from '@/composables/useToast'

const toast = useToast()
const loading = ref(true)

// Tab 壳页：演示加载/空状态（P1 FE2 接入记录 CRUD）
onShow(() => {
  loading.value = true
  setTimeout(() => {
    loading.value = false
  }, 600)
})

function onAction() {
  toast.info({ title: '记录功能 P1 接入' })
}
</script>

<style lang="scss" scoped>
.page-shell {
  padding: $space-md;
}
</style>
