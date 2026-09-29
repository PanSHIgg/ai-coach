import type { AdminLoginData, AdminRole } from '@/types/api'

const AUTH_KEY = 'ai_coach_admin_auth'

export interface AdminAuth {
  token: string
  role: AdminRole
  merchant_id: number | null
  username: string
}

export function getAuth(): AdminAuth | null {
  try {
    const raw = localStorage.getItem(AUTH_KEY)
    if (!raw) return null
    return JSON.parse(raw) as AdminAuth
  } catch {
    return null
  }
}

export function setAuth(data: AdminLoginData): void {
  localStorage.setItem(
    AUTH_KEY,
    JSON.stringify({
      token: data.token,
      role: data.role,
      merchant_id: data.merchant_id,
      username: data.username,
    } satisfies AdminAuth),
  )
}

export function clearAuth(): void {
  localStorage.removeItem(AUTH_KEY)
}

export function getToken(): string | null {
  return getAuth()?.token ?? null
}
