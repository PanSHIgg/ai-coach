/**
 * user store · 登录态 + 用户信息
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { LoginData, UserBrief, UserDetail } from '@/types/api'
import * as authApi from '@/api/auth'
import { getToken, saveToken, clearAuth } from '@/api/request'

export const useUserStore = defineStore('user', () => {
  const token = ref(getToken())
  const user = ref<UserBrief | null>(null)
  const detail = ref<UserDetail | null>(null)

  const isLogined = computed(() => !!token.value)
  const nickname = computed(() => user.value?.nickname || '减友')

  /** 登录成功：落 token + 用户信息 */
  function onLoginSuccess(data: LoginData) {
    saveToken(data.token, data.refresh_token)
    token.value = data.token
    user.value = data.user
  }

  /**
   * 微信登录。
   * 【假设】P0 开发态 Mock 登录：code 由调用方传入（mock 固定值），联调后换 wx.login 真 code。
   */
  async function login(code: string) {
    const data = await authApi.login({ code })
    onLoginSuccess(data)
    return data
  }

  /** 拉当前用户（进入首页 / 我的页时调用） */
  async function fetchMe() {
    detail.value = await authApi.getMe()
    if (detail.value) {
      user.value = { id: detail.value.id, nickname: detail.value.nickname, avatar_url: detail.value.avatar_url }
    }
    return detail.value
  }

  /** 退出：清存储回登录页 */
  function logout() {
    clearAuth()
    token.value = ''
    user.value = null
    detail.value = null
    uni.reLaunch({ url: '/pages/login/login' })
  }

  return { token, user, detail, isLogined, nickname, login, fetchMe, logout }
})
