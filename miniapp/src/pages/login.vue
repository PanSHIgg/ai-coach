<template>
  <view class="login">
    <image class="login__logo" src="/static/logo.png" mode="aspectFit" />
    <text class="login__title">AI 饮食管控教练</text>
    <text class="login__desc">拍一拍，热量全知道</text>
    <CButton class="login__btn" block :loading="loading" :disabled="!canWxLogin" @click="onLogin">微信一键登录</CButton>
    <!-- #ifndef MP-WEIXIN -->
    <text class="login__notice">当前不是微信小程序环境，无法获取微信登录凭证，请在微信中打开本小程序</text>
    <!-- #endif -->
    <text class="login__tip">登录即表示同意《用户协议》与《隐私政策》</text>
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { onLoad, onShow } from '@dcloudio/uni-app'
import { useUserStore } from '@/stores/user'
import { getToken } from '@/api/request'
import { useToast } from '@/composables/useToast'
import { track } from '@/utils/track'
import { LOGIN_PATH } from '@/utils/nav'

const userStore = useUserStore()
const toast = useToast()
const loading = ref(false)

/** 冷启动标记：登录页为未登录冷启动首屏，app_open 的 from 口径 */
let firstShow = true

/** 登录后回跳目标（来自 ?redirect=；非法/指向登录页自身时置空，防循环） */
const redirect = ref('')

/** 规范化 redirect：兼容「已解码」与「未解码」两种来源，只接受站内页面路径 */
function normalizeRedirect(raw?: string): string {
  if (!raw) return ''
  let path = raw
  if (!path.startsWith('/pages/')) {
    try {
      path = decodeURIComponent(raw)
    } catch {
      path = raw
    }
  }
  if (!path.startsWith('/pages/') || path === LOGIN_PATH || path.startsWith(`${LOGIN_PATH}?`)) return ''
  return path
}

onLoad((options) => {
  redirect.value = normalizeRedirect(options?.redirect)
})

// 已登录直接进：优先回跳原页，否则进首页
onShow(() => {
  // 判据取 storage 而非 userStore.isLogined：401 走的是 request.ts 的 clearAuth()，
  // 它只清 storage、不重置 store 里的 token ref，isLogined 会滞留 true，
  // 导致本页与 index 互相 reLaunch 成环（实测 4 分钟 350 条请求）。
  if (getToken()) {
    uni.reLaunch({ url: redirect.value || '/pages/index' })
    return
  }
  // 匿名可达：冷启动进入登录页也上报活跃，保证未登录活跃可观测
  track('app_open', { from: firstShow ? 'cold_start' : 'login' })
  firstShow = false
})

/**
 * 微信登录凭证（code）获取器 —— 只在小程序端装配。
 *
 * H5 构建里 #ifdef MP-WEIXIN 块被整段剔除，此处保持 null：
 * 按钮 disabled + 页面显式提示 + onLogin 直接拒绝，三处都可见。
 * 【禁止回退】不给 mock/固定 code 兜底——静默的假登录正是本轮排查的根源。
 */
let fetchWxCode: (() => Promise<string>) | null = null
// #ifdef MP-WEIXIN
fetchWxCode = () =>
  new Promise<string>((resolve, reject) => {
    uni.login({
      provider: 'weixin',
      success: (res) => {
        if (res.code) return resolve(res.code)
        // code 为空：无任何 toast 的盲区（游客模式受限/授权异常），必须可见
        const err = `wx.login 未返回 code：${res.errMsg || 'unknown'}`
        toast.error({ title: '获取微信登录凭证失败' })
        reject(Object.assign(new Error(err), { toasted: true }))
      },
      fail: (err) => {
        // uni.login 本身失败此前被外层静默吞掉，点登录无反馈难排查
        toast.error({ title: `微信登录调用失败：${err.errMsg || 'unknown'}` })
        reject(Object.assign(new Error(err.errMsg || 'uni.login fail'), { toasted: true }))
      },
    })
  })
// #endif

/** 当前构建是否支持微信一键登录（H5 = false） */
const canWxLogin = fetchWxCode !== null

async function onLogin() {
  if (loading.value) return // 防重复点击（CButton 亦已 loading 置灰）
  if (!fetchWxCode) {
    // 非微信端没有 code 来源（按钮已 disabled，此处是兜底）：
    // 直接拒绝并给出可见原因，禁止"点了没反应"的静默失败。
    toast.error({ title: '仅微信小程序支持登录，请在微信中打开本小程序' })
    return
  }
  loading.value = true
  try {
    // 微信端唯一登录路径：uni.login（wx.login）拿真 code 换 JWT，无任何 mock 兜底
    const code = await fetchWxCode()
    const data = await userStore.login(code)
    // 登录成功 / 新用户注册（留存 cohort 依赖 register + user.created_at）
    track('login', { from: 'wechat' })
    if (data.is_new) track('register', {})
    toast.success({ title: data.is_new ? '欢迎加入' : '欢迎回来' })
    // 登录后回跳：优先回原页（§3.3 / §13.2「登录后回跳原页」）；
    // 无 redirect 时维持默认落地页——未建档先去建档，已建档进首页
    if (redirect.value) {
      uni.reLaunch({ url: redirect.value })
    } else if (data.need_profile) {
      uni.reLaunch({ url: '/pages/profile/edit' })
    } else {
      uni.reLaunch({ url: '/pages/index' })
    }
  } catch (e) {
    // 登录接口是 silent 的，其错误不走 request 封装的 toast；上游已在 uni.login
    // 两个分支就地 toast，用 toasted 标记避免同一失败弹两次。
    if (!(e as { toasted?: boolean }).toasted) {
      toast.error({ title: (e as Error).message || '登录失败，请稍后重试' })
    }
  } finally {
    loading.value = false
  }
}
</script>

<style lang="scss" scoped>
.login {
  @include flex-center(column);

  min-height: 100vh;
  padding: 0 $space-lg;

  &__logo {
    width: 160rpx;
    height: 160rpx;
    margin-top: 26vh;
    margin-bottom: $space-lg;
    border-radius: $radius-lg;
    box-shadow: $shadow;
  }

  &__title {
    font-size: $t-32;
    font-weight: 500;
    color: $text-1;
  }

  &__desc {
    margin: $space-xs 0 $space-xl;
    font-size: $t-24;
    color: $text-2;
  }

  &__btn {
    width: 100%;
  }

  &__notice {
    width: 100%;
    margin-top: $space-md;
    font-size: $t-24;
    line-height: 1.5;
    text-align: center;
    color: $warn;
  }

  &__tip {
    margin-top: $space-md;
    font-size: $t-22;
    color: $text-3;
  }
}
</style>
