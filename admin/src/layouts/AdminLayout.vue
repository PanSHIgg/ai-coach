<template>
  <el-container class="layout">
    <el-aside width="220px" class="aside">
      <div class="logo">AI 饮食管控 · 管理后台</div>
      <el-menu :default-active="route.path" router background-color="#001529" text-color="#a6adb4" active-text-color="#22c55e">
        <el-menu-item v-for="m in menus" :key="m.path" :index="m.path">
          <el-icon><component :is="m.icon" /></el-icon>
          <span>{{ m.label }}</span>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="header">
        <span class="header-title">{{ route.meta.title ?? '' }}</span>
        <div class="header-right">
          <span class="username">{{ auth?.username }}（{{ roleLabel }}）</span>
          <el-button text type="primary" @click="onLogout">退出</el-button>
        </div>
      </el-header>
      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getAuth, clearAuth } from '@/composables/auth'
import type { AdminRole } from '@/types/api'

const route = useRoute()
const router = useRouter()

const auth = getAuth()
const role = auth?.role ?? 1

const roleLabel = computed(() => ({ 1: '超管', 2: '运营', 3: '商家' })[role] ?? '未知')

interface MenuItem {
  path: string
  label: string
  icon: string
  roles: AdminRole[]
}

/** 超管/运营看全部；商家角色只看订单与核销相关 */
const allMenus: MenuItem[] = [
  { path: '/dashboard', label: '运营看板', icon: 'Odometer', roles: [1, 2, 3] },
  { path: '/merchants', label: '商家审核', icon: 'Shop', roles: [1, 2] },
  { path: '/merchant-skus', label: '选品定价', icon: 'Goods', roles: [1, 2] },
  { path: '/coupon-pools', label: '券池管理', icon: 'Ticket', roles: [1, 2] },
  { path: '/orders', label: '订单监控', icon: 'List', roles: [1, 2, 3] },
]

const menus = allMenus.filter((m) => (m.roles as number[]).includes(role))

function onLogout(): void {
  clearAuth()
  router.push('/login')
}
</script>

<style scoped>
.layout {
  height: 100vh;
}

.aside {
  background-color: #001529;
}

.logo {
  height: 56px;
  line-height: 56px;
  text-align: center;
  color: #fff;
  font-size: 15px;
  font-weight: 600;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.aside :deep(.el-menu) {
  border-right: none;
}

.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #fff;
  border-bottom: 1px solid #e5e7eb;
}

.header-title {
  font-size: 16px;
  font-weight: 600;
  color: #1f2937;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.username {
  font-size: 14px;
  color: #6b7280;
}

.main {
  background: #f5f6f8;
}
</style>
