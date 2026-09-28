<template>
  <view class="page-shell">
    <CSkeleton v-if="loading" type="card" />
    <CEmpty v-else text="还没有动态，发一条吧" @action="onAction" />
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { useToast } from '@/composables/useToast'

const toast = useToast()
const loading = ref(true)

// Tab 壳页：社区动态（P4 FE5 接入）
onShow(() => {
  loading.value = true
  setTimeout(() => {
    loading.value = false
  }, 600)
})

function onAction() {
  toast.info({ title: '社区功能 P4 接入' })
}
</script>

<style lang="scss" scoped>
.page-shell {
  padding: $space-md;
}
</style>
