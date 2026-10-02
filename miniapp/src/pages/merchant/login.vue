<template>
  <view class="ml">
    <!-- 1. 品牌头部 -->
    <view class="ml__hero">
      <text class="ml__title">商家后台</text>
      <text class="ml__desc">登录后管理选品、定价与核销</text>
    </view>

    <!-- 2. 登录方式切换：账号密码 / 手机验证码（占位） -->
    <view class="ml__seg">
      <text
        class="ml__seg-item"
        :class="{ 'ml__seg-item--active': mode === 'password' }"
        @tap="mode = 'password'"
      >
        账号密码
      </text>
      <text
        class="ml__seg-item"
        :class="{ 'ml__seg-item--active': mode === 'sms' }"
        @tap="mode = 'sms'"
      >
        手机验证码
      </text>
    </view>

    <!-- 3. 账号密码登录表单 -->
    <view v-if="mode === 'password'" class="ml__form">
      <CField label="商家账号" required :error="errors.username">
        <CInput
          v-model="form.username"
          placeholder="请输入商家账号"
          :maxlength="40"
          @confirm="onSubmit"
        />
      </CField>
      <CField label="密码" required :error="errors.password">
        <CInput
          v-model="form.password"
          placeholder="请输入密码"
          :maxlength="64"
          @confirm="onSubmit"
        />
      </CField>

      <text v-if="formError" class="ml__error">{{ formError }}</text>

      <CButton class="ml__btn" block size="lg" :loading="loading" @click="onSubmit">登录</CButton>
      <text class="ml__tip">仅限已入驻商家使用，账号由平台开通</text>
    </view>

    <!-- 4. 手机验证码登录占位（契约无该接口） -->
    <view v-else class="ml__placeholder">
      <text class="ml__placeholder-title">手机验证码登录暂未开放</text>
      <text class="ml__placeholder-desc">
        当前接口契约未提供短信验证码登录能力，请使用账号密码登录。
      </text>
      <CButton class="ml__btn" block size="lg" type="secondary" @click="mode = 'password'">
        返回账号密码登录
      </CButton>
    </view>
  </view>
</template>

<script setup lang="ts">
/**
 * G11 · 商家后台登录（独立入口）
 * 依据：docs/split/01-整体架构与产品需求.md L159（页面 24 商家后台登录：账号密码/手机验证码）
 * 契约：POST /api/merchant/login（MerchantLoginIn → MerchantLoginData，见 api/merchantAdmin.ts）
 * 【假设】手机验证码登录契约缺失 → 以占位 UI 提示「暂未开放」（任务要求）。
 * 【限制】组件库 CInput 不支持 password 属性（组件冻结只读），密码框按普通文本输入展示。
 */
import { reactive, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { merchantLogin, saveMerchantToken, getMerchantToken } from '@/api/merchantAdmin'
import { useToast } from '@/composables/useToast'

const toast = useToast()

/** 登录方式：账号密码 / 手机验证码（占位） */
const mode = ref<'password' | 'sms'>('password')
const loading = ref(false)
const form = reactive({ username: '', password: '' })
const errors = reactive({ username: '', password: '' })
const formError = ref('')

/** 表单校验：账号/密码必填，密码不少于 6 位 */
function validate(): boolean {
  errors.username = form.username.trim() ? '' : '请输入商家账号'
  if (!form.password) {
    errors.password = '请输入密码'
  } else if (form.password.length < 6) {
    errors.password = '密码不少于 6 位'
  } else {
    errors.password = ''
  }
  return !errors.username && !errors.password
}

async function onSubmit() {
  if (loading.value) return
  formError.value = ''
  if (!validate()) return

  loading.value = true
  try {
    // silent：登录失败文案走表单内联错误，避免 toast 叠加
    const data = await merchantLogin(
      { username: form.username.trim(), password: form.password },
      true,
    )
    saveMerchantToken(data.token)
    toast.success({ title: '登录成功' })
    uni.reLaunch({ url: '/pages/merchant/admin' })
  } catch (e) {
    formError.value = (e as Error).message || '登录失败，请重试'
  } finally {
    loading.value = false
  }
}

// 已持有商家 token：直接进入商家后台（防止重复登录）
onShow(() => {
  if (getMerchantToken()) uni.reLaunch({ url: '/pages/merchant/admin' })
})
</script>

<style lang="scss" scoped>
.ml {
  min-height: 100vh;
  padding: 0 $space-lg;
  background: $bg;

  // 1. 品牌头部
  &__hero {
    padding-top: 18vh;
    margin-bottom: $space-xl;
    text-align: center;
  }

  &__title {
    display: block;
    font-size: $t-32;
    font-weight: 500;
    color: $text-1;
  }

  &__desc {
    display: block;
    margin-top: $space-xs;
    font-size: $t-24;
    color: $text-2;
  }

  // 2. 登录方式切换
  &__seg {
    display: flex;
    gap: $space-sm;
    margin-bottom: $space-lg;
  }

  &__seg-item {
    flex: 1;
    padding: 16rpx 0;
    font-size: $t-24;
    color: $text-2;
    text-align: center;
    background: $card;
    border: 1rpx solid $border;
    border-radius: $radius-sm;

    &--active {
      color: $brand-dark;
      background: rgba($brand, 0.1);
      border-color: $brand;
    }
  }

  // 3. 表单
  &__form,
  &__placeholder {
    padding: $space-lg;
    background: $card;
    border-radius: $radius;
    box-shadow: $shadow;
  }

  &__error {
    display: block;
    margin-bottom: $space-sm;
    font-size: $t-22;
    color: $danger;
  }

  &__btn {
    width: 100%;
    margin-top: $space-sm;
  }

  &__tip {
    display: block;
    margin-top: $space-md;
    font-size: $t-22;
    color: $text-3;
    text-align: center;
  }

  // 4. 占位
  &__placeholder-title {
    display: block;
    font-size: $t-28;
    font-weight: 500;
    color: $text-1;
    text-align: center;
  }

  &__placeholder-desc {
    display: block;
    margin: $space-sm 0 $space-lg;
    font-size: $t-24;
    color: $text-2;
    text-align: center;
  }
}
</style>