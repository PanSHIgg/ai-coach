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
          meta: { title: '运营看板' },
        },
        {
          path: 'merchants',
          name: 'merchants',
          component: () => import('@/views/MerchantsView.vue'),
          meta: { title: '商家审核' },
        },
        {
          path: 'merchant-skus',
          name: 'merchant-skus',
          component: () => import('@/views/MerchantSkusView.vue'),
          meta: { title: '选品定价' },
        },
        {
          path: 'coupon-pools',
          name: 'coupon-pools',
          component: () => import('@/views/CouponPoolsView.vue'),
          meta: { title: '券池管理' },
        },
        {
          path: 'orders',
          name: 'orders',
          component: () => import('@/views/OrdersView.vue'),
          meta: { title: '订单监控' },
        },
        {
          path: 'content-audit',
          name: 'content-audit',
          component: () => import('@/views/ContentAuditView.vue'),
          meta: { title: '内容审核' },
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
  return true
})

router.afterEach((to) => {
  const base = 'AI 饮食管控教练 · 管理后台'
  document.title = to.meta.title ? `${String(to.meta.title)} - ${base}` : base
})

export default router
