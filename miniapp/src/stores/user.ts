/**
 * user store · 登录态 + 用户信息 + 身体档案
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { LoginData, UserBrief, UserDetail, BodyProfileOut } from '@/types/api'
import * as authApi from '@/api/auth'
import { getBodyProfile } from '@/api/profile'
import { getToken, saveToken, clearAuth } from '@/api/request'

export const useUserStore = defineStore('user', () => {
  const token = ref(getToken())
  const user = ref<UserBrief | null>(null)
  const detail = ref<UserDetail | null>(null)

  /** 身体档案（首页核心指标 / 建档引导数据源） */
  const profile = ref<BodyProfileOut | null>(null)
  /** 是否已拉取过档案（避免 onShow 重复请求） */
  const profileLoaded = ref(false)
  /** 是否未建档（未建档时首页展示建档引导） */
  const needProfile = ref(false)

  const isLogined = computed(() => !!token.value)
  const nickname = computed(() => user.value?.nickname || '减友')
  /** 权益档位：0基础 1进阶 2高级 3终身（§5.5 版本标签） */
  const tier = computed(() => detail.value?.benefit?.tier ?? 0)

  /** 登录成功：落 token + 用户信息 + 建档标记 */
  function onLoginSuccess(data: LoginData) {
    saveToken(data.token, data.refresh_token)
    token.value = data.token
    user.value = data.user
    needProfile.value = data.need_profile
    // 换账号后档案需重新拉取
    profile.value = null
    profileLoaded.value = false
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
    try {
      detail.value = await authApi.getMe()
      if (detail.value) {
        user.value = {
          id: detail.value.id,
          nickname: detail.value.nickname,
          avatar_url: detail.value.avatar_url,
        }
      }
    } catch (e) {
      // 错误信息已由 request 封装 toast
    }
    return detail.value
  }

  /**
   * 拉身体档案。
   * 后端未建档时返回 data=null（非错误），据此置 needProfile 引导建档。
   */
  async function fetchProfile() {
    try {
      const p = await getBodyProfile()
      profile.value = p
      needProfile.value = !p
    } catch (e) {
      // 网络异常等：保留旧档案，不误判为未建档
    } finally {
      profileLoaded.value = true
    }
    return profile.value
  }

  /** 档案保存成功后回填（建档页调用，避免再发一次请求） */
  function setProfile(p: BodyProfileOut) {
    profile.value = p
    needProfile.value = false
    profileLoaded.value = true
  }

  /** 退出：清存储回登录页 */
  function logout() {
    clearAuth()
    token.value = ''
    user.value = null
    detail.value = null
    profile.value = null
    needProfile.value = false
    profileLoaded.value = false
    uni.reLaunch({ url: '/pages/login/login' })
  }

  return {
    token,
    user,
    detail,
    profile,
    profileLoaded,
    needProfile,
    isLogined,
    nickname,
    tier,
    login,
    fetchMe,
    fetchProfile,
    setProfile,
    logout,
  }
})