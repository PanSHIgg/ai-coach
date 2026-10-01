/**
 * offline.ts · 离线写操作队列（F-03）
 *
 * 依据：全栈交付文档 §2.4「网络异常：全局 toast，关键操作（记录、订单）本地缓存，恢复后重试。」
 *
 * 设计要点：
 * - 仅对**关键写操作**（饮食 meal 增删改 / 运动 sport 新建 / 体重 weight 新建与删除 / 订单 order 创建）
 *   在**网络类失败**时入队；未知/非白名单接口不入队（由 request.ts 只在网络失败分支调用）。
 * - 队列持久化在 uni.setStorageSync（键 ai_coach_offline_queue），每条含唯一 id / 时间戳 / 顺序 seq。
 * - 去重：以 `method + path + JSON(data)` 为幂等键，同一操作不重复入队。
 * - 恢复重放：监听 uni.onNetworkStatusChange（恢复在线时按 seq 顺序重放，成功移除、失败保留），
 *   App 启动时探测网络并尝试重放。
 * - 失败阈值 MAX_RETRY：单条重试 ≥3 次后保留在队列、提示用户且不再自动重试，避免死循环。
 * - 全程 try/catch 降级，存储/网络异常均不阻塞业务流程。
 */
import { request, setNetworkFailHook } from '@/api/request'
import { useToast } from '@/composables/useToast'

/** 队列本地存储键 */
const STORAGE_KEY = 'ai_coach_offline_queue'
/** 单条最大自动重试次数，超过后保留并提示（避免死循环） */
const MAX_RETRY = 3

type HttpMethod = 'GET' | 'POST' | 'PUT' | 'DELETE'

/** 离线队列中的一条写操作 */
export interface OfflineTask {
  /** 唯一 id */
  id: string
  /** 入队顺序（单调递增，重放按此排序） */
  seq: number
  /** 幂等/去重键：method + path + data */
  key: string
  path: string
  method: HttpMethod
  data?: object
  /** 入队时间戳（ms） */
  createdAt: number
  /** 已重试次数 */
  retryCount: number
  /** 是否已就「多次失败」提示过（避免重复打扰） */
  notified: boolean
}

/** 关键写操作白名单（method + path 精确/正则匹配） */
const WRITE_WHITELIST: Array<{ method: HttpMethod; pattern: RegExp }> = [
  { method: 'POST', pattern: /^\/api\/meal$/ },
  { method: 'PUT', pattern: /^\/api\/meal\/\d+$/ },
  { method: 'DELETE', pattern: /^\/api\/meal\/\d+$/ },
  { method: 'POST', pattern: /^\/api\/sport$/ },
  { method: 'POST', pattern: /^\/api\/weight$/ },
  { method: 'DELETE', pattern: /^\/api\/weight\/\d+$/ },
  { method: 'POST', pattern: /^\/api\/order$/ },
]

let initialized = false
let replaying = false

/** 生成唯一 id（无 crypto.randomUUID，用时间戳 + 随机串） */
function genId(): string {
  return `off-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

/** 是否命中关键写操作白名单 */
function isWhitelisted(method: string, path: string): boolean {
  return WRITE_WHITELIST.some((w) => w.method === method && w.pattern.test(path))
}

/** 幂等/去重键 */
function buildKey(method: string, path: string, data?: object): string {
  let payload = 'null'
  try {
    payload = JSON.stringify(data ?? null)
  } catch {
    payload = String(data)
  }
  return `${method} ${path} ${payload}`
}

/** 读取本地队列（异常降级为空队列） */
function readQueue(): OfflineTask[] {
  try {
    const raw = uni.getStorageSync(STORAGE_KEY)
    if (!raw) return []
    const arr = typeof raw === 'string' ? JSON.parse(raw) : raw
    return Array.isArray(arr) ? (arr as OfflineTask[]) : []
  } catch {
    return []
  }
}

/** 写回本地队列（失败返回 false） */
function writeQueue(queue: OfflineTask[]): boolean {
  try {
    uni.setStorageSync(STORAGE_KEY, JSON.stringify(queue))
    return true
  } catch {
    return false
  }
}

/** 移除指定任务（重放成功后调用） */
function removeTask(id: string): void {
  writeQueue(readQueue().filter((t) => t.id !== id))
}

/** 重试计数 +1；达到阈值时提示一次（任务保留，不再自动重试） */
function bumpRetry(id: string): void {
  const queue = readQueue()
  const task = queue.find((t) => t.id === id)
  if (!task) return
  task.retryCount += 1
  if (task.retryCount >= MAX_RETRY && !task.notified) {
    task.notified = true
    useToast().error({ title: '离线内容多次同步失败，请检查网络后再试' })
  }
  writeQueue(queue)
}

/** 探测当前是否有网络（取不到结果时按在线处理，交由请求自身判定） */
function checkOnline(): Promise<boolean> {
  return new Promise((resolve) => {
    try {
      uni.getNetworkType({
        success: (res) => resolve(!!res.networkType && res.networkType !== 'none'),
        fail: () => resolve(true),
      })
    } catch {
      resolve(true)
    }
  })
}

/**
 * 将一次关键写操作写入离线队列（仅网络类失败时由 request.ts 调用）。
 * @returns 是否**新入队**（命中白名单且未重复）；调用方可据此替换通用网络错误 toast
 */
export function enqueueOffline(path: string, method: HttpMethod, data?: object): boolean {
  if (!isWhitelisted(method, path)) return false
  try {
    const key = buildKey(method, path, data)
    const queue = readQueue()
    // 去重：同一操作（含重放失败回写）不重复入队
    if (queue.some((t) => t.key === key)) return false

    const seq = queue.reduce((max, t) => Math.max(max, t.seq), 0) + 1
    queue.push({
      id: genId(),
      seq,
      key,
      path,
      method,
      data,
      createdAt: Date.now(),
      retryCount: 0,
      notified: false,
    })
    if (!writeQueue(queue)) return false
    useToast().info({ title: '网络异常，已离线暂存，恢复后自动重试' })
    return true
  } catch {
    return false
  }
}

/**
 * 按 seq 顺序重放队列：成功移除、失败保留并计数；离线或达阈值时停止本轮。
 * 并发调用会去重（同一时刻仅一次重放）。
 */
export async function replayOfflineQueue(): Promise<void> {
  if (replaying) return
  if (!(await checkOnline())) return
  replaying = true
  let synced = 0
  try {
    const pending = readQueue().sort((a, b) => a.seq - b.seq)
    for (const item of pending) {
      if (!(await checkOnline())) break
      const current = readQueue().find((t) => t.id === item.id)
      // 已被移除 / 已达重试阈值 → 跳过（保留但不再自动重试，避免死循环）
      if (!current || current.retryCount >= MAX_RETRY) continue
      try {
        await request(current.path, { method: current.method, data: current.data, silent: true })
        removeTask(current.id)
        synced += 1
      } catch {
        bumpRetry(current.id)
      }
    }
  } finally {
    replaying = false
  }
  if (synced > 0) useToast().success({ title: '离线记录已自动同步' })
}

/**
 * 注册网络恢复监听，并在启动时尝试重放一次（App onLaunch 调用）。
 * 幂等：重复调用只注册一次。
 */
export function setupOfflineQueue(): void {
  if (initialized) return
  initialized = true
  try {
    uni.onNetworkStatusChange((res) => {
      if (res.isConnected) void replayOfflineQueue()
    })
  } catch {
    /* 平台不支持网络监听时忽略 */
  }
  // 启动探测：在线才重放，避免离线态误增重试次数
  void checkOnline().then((online) => {
    if (online) void replayOfflineQueue()
  })
}

// 注册网络失败入队钩子到 request.ts（模块加载即注册；App 入口 import 本模块时生效）
setNetworkFailHook(enqueueOffline)