<script setup lang="ts">
import { onLaunch } from '@dcloudio/uni-app'
import { useUserStore } from '@/stores/user'
import { setupOfflineQueue } from '@/utils/offline'

onLaunch(() => {
  // 启动恢复登录态（token 在 store 初始化时已从 storage 读取）
  const userStore = useUserStore()
  console.log('[app] launched, logined =', userStore.isLogined)
  // F-03：注册网络恢复监听并尝试重放离线队列（关键写操作离线缓存 → 恢复后重试）
  setupOfflineQueue()
})
</script>

<style lang="scss">
/* 全局基础样式：全工程仅此一次 @import（page CSS 变量 / reset / keyframes） */
@import '@/styles/base.scss';
</style>
