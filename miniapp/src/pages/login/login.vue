<template>
  <view class="login">
    <view class="login__logo">🥗</view>
    <text class="login__title">AI 饮食管控教练</text>
    <text class="login__desc">拍一拍，热量全知道</text>
    <CButton class="login__btn" block :loading="loading" @click="onLogin">微信一键登录</CButton>
    <text class="login__tip">登录即表示同意《用户协议》与《隐私政策》</text>
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { useUserStore } from '@/stores/user'
import { useToast } from '@/composables/useToast'
import { track } from '@/utils/track'

const userStore = useUserStore()
const toast = useToast()
const loading = ref(false)

/** 冷启动标记：登录页为未登录冷启动首屏，app_open 的 from 口径 */
let firstShow = true

// 已登录直接进首页
onShow(() => {
  if (userStore.isLogined) {
    uni.reLaunch({ url: '/pages/index/index' })
    return
  }
  // 匿名可达：冷启动进入登录页也上报活跃，保证未登录活跃可观测
  track('app_open', { from: firstShow ? 'cold_start' : 'login' })
  firstShow = false
})

async function onLogin() {
  if (loading.value) return // 防重复点击（CButton 亦已 loading 置灰）
  loading.value = true
  try {
    // 【假设】P0 开发态 Mock 登录：VITE_USE_MOCK=true 时用固定 code 换 Mock 数据；
    // 正式联调（use_mock≠true 且在微信端）走 uni.login 拿真 code
    let code = 'mock-code'
    // #ifdef MP-WEIXIN
    if (import.meta.env.VITE_USE_MOCK !== 'true') {
      code = await new Promise<string>((resolve, reject) => {
        uni.login({
          provider: 'weixin',
          success: (res) => resolve(res.code || ''),
          fail: reject,
        })
      })
    }
    // #endif
    const data = await userStore.login(code)
    // 登录成功 / 新用户注册（留存 cohort 依赖 register + user.created_at）
    track('login', { from: 'wechat' })
    if (data.is_new) track('register', {})
    toast.success({ title: data.is_new ? '欢迎加入' : '欢迎回来' })
    // 未建档 → 先去建档；已建档 → 进首页
    if (data.need_profile) {
      uni.reLaunch({ url: '/pages/profile/edit' })
    } else {
      uni.reLaunch({ url: '/pages/index/index' })
    }
  } catch (e) {
    // 错误信息已由 request 封装 toast，此处静默
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
    @include flex-center;

    width: 160rpx;
    height: 160rpx;
    margin-top: 26vh;
    margin-bottom: $space-lg;
    font-size: 80rpx;
    background: $card;
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

  &__tip {
    margin-top: $space-md;
    font-size: $t-22;
    color: $text-3;
  }
}
</style>
