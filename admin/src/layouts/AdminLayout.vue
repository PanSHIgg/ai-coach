<template>
  <el-container class="layout" :class="{ 'is-collapsed': collapsed }">
    <el-aside :width="asideWidth" class="aside">
      <div class="logo">
        <span class="logo-mark">AI</span>
        <span class="logo-text">AI 饮食管控 · 管理后台</span>
      </div>
      <el-menu
        :default-active="route.path"
        router
        :collapse="collapsed"
        :collapse-transition="false"
        background-color="#001529"
        text-color="#a6adb4"
        active-text-color="#22c55e"
      >
        <el-menu-item v-for="m in menus" :key="m.path" :index="m.path">
          <el-icon><component :is="m.icon" /></el-icon>
          <template #title>{{ m.label }}</template>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="header">
        <div class="header-left">
          <el-button class="menu-toggle" text aria-label="收起/展开侧栏" @click="collapsed = !collapsed">
            <el-icon><component :is="collapsed ? 'Expand' : 'Fold'" /></el-icon>
          </el-button>
          <span class="header-title">{{ route.meta.title ?? '' }}</span>
        </div>
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
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getAuth, clearAuth } from '@/composables/auth'
import type { AdminRole } from '@/types/api'

const route = useRoute()
const router = useRouter()

const auth = getAuth()
const role = auth?.role ?? 1

const roleLabel = computed(() => ({ 1: '超管', 2: '运营', 3: '商家' })[role] ?? '未知')

/** 窄屏默认折叠为图标栏；宽屏默认展开。可由页头按钮切换。 */
const collapsed = ref(typeof window !== 'undefined' && window.innerWidth < 992)
const asideWidth = computed(() => (collapsed.value ? '64px' : '220px'))

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
  { path: '/content-audit', label: '内容审核', icon: 'Checked', roles: [1, 2] },
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

/* 内容容器可收缩，避免被宽表格撑破视口（375 窄屏关键） */
.layout > .el-container {
  min-width: 0;
}

.aside {
  background-color: #001529;
  transition: width 0.2s ease;
  overflow: hidden;
}

.logo {
  height: 56px;
  line-height: 56px;
  text-align: center;
  color: #fff;
  font-size: 15px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.logo-mark {
  display: none;
}

.layout.is-collapsed .logo-text {
  display: none;
}

.layout.is-collapsed .logo-mark {
  display: inline;
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

.header-left {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
}

.menu-toggle {
  display: none;
}

.header-title {
  font-size: 16px;
  font-weight: 600;
  color: #1f2937;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.username {
  font-size: 14px;
  color: #6b7280;
}

.main {
  background: #f5f6f8;
  min-width: 0;
  overflow-x: hidden;
}

/* 表格类页面在窄屏内部横向滚动，不撑破布局 */
.main :deep(.el-card__body) {
  overflow-x: auto;
}

@media (max-width: 992px) {
  .menu-toggle {
    display: inline-flex;
  }

  .header {
    padding: 0 12px;
  }

  .main {
    padding: 12px;
  }
}

@media (max-width: 576px) {
  .username {
    display: none;
  }
}
</style>
