import axios, { AxiosError, type AxiosInstance } from 'axios'
import { ElMessage } from 'element-plus'
import { clearAuth, getToken } from '@/composables/auth'
import type { Envelope } from '@/types/api'

/** 创建 axios 实例；/api 由 vite proxy 转发到 http://127.0.0.1:8000 */
export const client: AxiosInstance = axios.create({
  baseURL: '/api',
  timeout: 10000,
})

function gotoLogin(): void {
  clearAuth()
  if (!window.location.hash.startsWith('#/login')) {
    window.location.hash = '#/login'
  }
}

client.interceptors.request.use((config) => {
  const token = getToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

client.interceptors.response.use(
  (resp) => {
    const body = resp.data as Envelope
    if (body && typeof body === 'object' && 'code' in body && body.code !== 0) {
      if (body.code === 1001) {
        gotoLogin()
      }
      ElMessage.error(body.message || '请求失败')
      return Promise.reject(new Error(body.message || '请求失败'))
    }
    return resp
  },
  (error: AxiosError<Envelope>) => {
    if (error.response) {
      const status = error.response.status
      if (status === 401) {
        gotoLogin()
        ElMessage.error('登录已过期，请重新登录')
      } else {
        const msg = error.response.data?.message || error.message || '请求失败'
        ElMessage.error(msg)
      }
      return Promise.reject(new Error(error.response.data?.message || error.message))
    }
    // 无响应（后端未启动等网络错误）：静默 reject，由页面层走 fallback 演示数据
    return Promise.reject(error)
  },
)

/** 拆包：取 Envelope.data */
export async function unwrap<T>(p: Promise<{ data: Envelope<T> }>): Promise<T> {
  const resp = await p
  return resp.data.data as T
}

/** 是否为无响应的网络错误（用于页面 fallback 判断） */
export function isNetworkError(err: unknown): boolean {
  return axios.isAxiosError(err) && !err.response
}
