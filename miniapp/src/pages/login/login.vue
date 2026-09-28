<template>
  <view class="login">
    <view class="login__logo">🥗</view>
    <text class="login__title">AI 饮食管控教练</text>
    <text class="login__desc">拍一拍，热量全知道</text>
    <CButton class="login__btn" block :loading="loading" @click="onLogin">微信一键登录</CButton>
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { useUserStore } from '@/stores/user'
import { useToast } from '@/composables/useToast'

const userStore = useUserStore()
const toast = useToast()
const loading = ref(false)

// 已登录直接进首页
onShow(() => {
  if (userStore.isLogined) {
    uni.reLaunch({ url: '/pages/index/index' })
  }
})

async function onLogin() {
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
    toast.success({ title: data.is_new ? '欢迎加入' : '欢迎回来' })
    uni.reLaunch({ url: '/pages/index/index' })
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
    margin-top: 30vh;
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
}
</style>
