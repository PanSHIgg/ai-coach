import { createRouter, createWebHashHistory } from 'vue-router'
import { getAuth } from '@/composables/auth'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: { title: '登录' },
    },
    {
      path: '/',
      component: () => import('@/layouts/AdminLayout.vue'),
      redirect: '/dashboard',
      children: [
        {
          path: 'dashboard',
          name: 'dashboard',
          component: () => import('@/views/DashboardView.vue'),
          meta: { title: '运营看板', roles: [1, 2, 3] },
        },
        {
          path: 'merchants',
          name: 'merchants',
          component: () => import('@/views/MerchantsView.vue'),
          meta: { title: '商家审核', roles: [1, 2] },
        },
        {
          path: 'merchant-skus',
          name: 'merchant-skus',
          component: () => import('@/views/MerchantSkusView.vue'),
          meta: { title: '选品定价', roles: [1, 2] },
        },
        {
          path: 'sku-catalog',
          name: 'sku-catalog',
          component: () => import('@/views/SkuCatalogView.vue'),
          meta: { title: '标准目录', roles: [1, 2] },
        },
        {
          path: 'coupon-pools',
          name: 'coupon-pools',
          component: () => import('@/views/CouponPoolsView.vue'),
          meta: { title: '券池管理', roles: [1, 2] },
        },
        {
          path: 'orders',
          name: 'orders',
          component: () => import('@/views/OrdersView.vue'),
          meta: { title: '订单监控', roles: [1, 2, 3] },
        },
        {
          path: 'content-audit',
          name: 'content-audit',
          component: () => import('@/views/ContentAuditView.vue'),
          meta: { title: '内容审核', roles: [1, 2] },
        },
        {
          path: 'accounts',
          name: 'accounts',
          component: () => import('@/views/AccountsView.vue'),
          meta: { title: '账号管理', roles: [1, 2] },
        },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/dashboard' },
  ],
})

router.beforeEach((to) => {
  const auth = getAuth()
  if (to.name !== 'login' && !auth) {
    return { name: 'login' }
  }
  if (to.name === 'login' && auth) {
    return { name: 'dashboard' }
  }
  // 角色门禁：与 AdminLayout 菜单可见性保持一致，防止越权直达
  const roles = to.meta.roles as number[] | undefined
  if (roles && auth && !roles.includes(auth.role)) {
    return { name: 'dashboard' }
  }
  return true
})

router.afterEach((to) => {
  const base = 'AI 饮食管控教练 · 管理后台'
  document.title = to.meta.title ? `${String(to.meta.title)} - ${base}` : base
})

export default router
