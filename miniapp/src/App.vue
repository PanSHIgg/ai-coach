<script setup lang="ts">
import { onLaunch } from '@dcloudio/uni-app'
import { useUserStore } from '@/stores/user'

onLaunch(() => {
  // 启动恢复登录态（token 在 store 初始化时已从 storage 读取）
  const userStore = useUserStore()
  console.log('[app] launched, logined =', userStore.isLogined)
})
</script>

<style lang="scss">
/* 全局基础样式：全工程仅此一次 @import（page CSS 变量 / reset / keyframes） */
@import '@/styles/base.scss';
</style>
