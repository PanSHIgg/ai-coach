/**
 * nav.ts · 登录拦截统一跳转（未登录先跳登录页，登录后回跳原页）
 *
 * 依据：主文档 §3.3「首页 → 任何需要登录的页，未登录先跳 /pages/login，登录后回跳原页」、
 *       §13.2「未登录访问需登录页：先跳登录，登录成功回跳原页」。
 *
 * - 跳登录时携带 `?redirect=<encodeURIComponent(当前页面完整路径含 query)>`。
 * - 登录页消费 redirect：合法则 reLaunch 回该页，否则维持默认落地页。
 * - 不回跳登录页自身，防循环。
 */

/** 登录页路由 */
export const LOGIN_PATH = '/pages/login'

/** 取当前页面完整路径（含 query），无法获取时返回空串 */
function currentFullPath(): string {
  let pages: unknown[] = []
  try {
    pages = getCurrentPages()
  } catch {
    return ''
  }
  if (!pages.length) return ''
  const cur = pages[pages.length - 1] as {
    route?: string
    options?: Record<string, unknown>
    $page?: { fullPath?: string; route?: string; options?: Record<string, unknown> }
  }
  // 小程序侧 $page.fullPath 最完整（含 query）；H5/兜底用 route + options 拼装
  const fullPath = cur.$page?.fullPath
  if (fullPath) return fullPath.startsWith('/') ? fullPath : `/${fullPath}`
  const route = cur.route || cur.$page?.route || ''
  if (!route) return ''
  const options = cur.options || cur.$page?.options || {}
  const qs = Object.keys(options)
    .map((k) => `${encodeURIComponent(k)}=${encodeURIComponent(String(options[k]))}`)
    .join('&')
  const path = route.startsWith('/') ? route : `/${route}`
  return qs ? `${path}?${qs}` : path
}

/** 构造带 redirect 的登录页地址（当前页即登录页或取不到路径时不带 redirect） */
export function loginUrlWithRedirect(): string {
  const path = currentFullPath()
  if (!path || path === LOGIN_PATH || path.startsWith(`${LOGIN_PATH}?`)) return LOGIN_PATH
  return `${LOGIN_PATH}?redirect=${encodeURIComponent(path)}`
}

/** 未登录/登录过期统一跳登录页（登录成功后可回跳原页） */
export function redirectToLogin(): void {
  uni.reLaunch({ url: loginUrlWithRedirect() })
}