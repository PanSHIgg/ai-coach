/**
 * track.ts · F3 前端埋点统一封装
 *
 * 依据：docs/埋点与指标口径.md（事件名清单 / 属性名口径）、
 *      接口 POST /api/track（TrackIn/TrackEventIn，批量 1~50，允许匿名）。
 *
 * 设计要点：
 * - track(event, properties?) 默认写入内存缓冲，延迟合并批量上报（≤50 条/批），可 flush() 立即上报。
 * - device_id 本地生成并持久化（uni.getStorageSync），匿名事件（scan_in 等）也能做设备级去重。
 * - platform：小程序=1 / H5=2（条件编译，小程序构建不含 H5 分支，反之亦然）。
 * - 匿名可用：不带 token 也能上报（后端 get_optional_user 自动关联或置空）；带 token 时自动附 Bearer。
 * - 失败静默降级：任何异常（网络失败 / 存储异常）都在内部 try/catch 丢弃，绝不阻塞 UI、不弹错。
 * - mp-weixin：额外镜像到微信自定义分析 wx.reportEvent（可用时，条件编译），失败忽略。
 */
import { BASE_URL, getToken } from '@/api/request'
import type { TrackEventIn, TrackIn } from '@/types/api'

/** device_id 本地存储键 */
const DEVICE_ID_KEY = 'ai_coach_device_id'
/** 单批上限（契约：events 1~50 条） */
const MAX_BATCH = 50
/** 首条入队后的合并延迟（ms），避免每条事件一次请求 */
const FLUSH_DELAY = 3000
/** 缓冲上限：超出丢最旧，防止弱网长期失败导致内存膨胀 */
const BUFFER_CAP = 200

/** 平台：小程序=1 / H5=2（契约 platform 口径） */
let PLATFORM: 1 | 2 = 1
// #ifdef H5
PLATFORM = 2
// #endif

/** 排队中的事件；occurred_at 在入队时打点，避免延迟上报造成时间漂移 */
const buffer: TrackEventIn[] = []
let flushing = false
let timer: ReturnType<typeof setTimeout> | null = null

/** 生成设备 id（无 crypto.randomUUID，用时间戳 + 随机串） */
function genDeviceId(): string {
  return `dev-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

/** 读取/初始化持久化 device_id（匿名事件跨端识别依赖） */
function getDeviceId(): string {
  try {
    const id = uni.getStorageSync(DEVICE_ID_KEY) as string
    if (id) return id
    const next = genDeviceId()
    uni.setStorageSync(DEVICE_ID_KEY, next)
    return next
  } catch {
    // 存储异常降级为内存态 id（不崩溃）
    return genDeviceId()
  }
}

/** mp-weixin：镜像事件到微信自定义分析（wx.reportEvent 可用时），失败静默 */
function reportToWx(event: string, properties: Record<string, unknown>): void {
  // #ifdef MP-WEIXIN
  try {
    const g = globalThis as unknown as {
      wx?: { reportEvent?: (name: string, data?: Record<string, unknown>) => void }
    }
    g.wx?.reportEvent?.(event, properties)
  } catch {
    /* 平台侧埋点失败不影响业务 */
  }
  // #endif
}

/**
 * 记录一个事件。
 * @param event 事件名（snake_case，见 docs/埋点与指标口径.md §2）
 * @param properties 事件属性（固定名以支撑报表口径）
 */
export function track(event: string, properties: Record<string, unknown> = {}): void {
  if (!event) return
  try {
    buffer.push({ event, properties, occurred_at: new Date().toISOString() })
    if (buffer.length > BUFFER_CAP) buffer.splice(0, buffer.length - BUFFER_CAP)
    reportToWx(event, properties)

    if (buffer.length >= MAX_BATCH) {
      void flush()
      return
    }
    if (!timer) {
      timer = setTimeout(() => {
        timer = null
        void flush()
      }, FLUSH_DELAY)
    }
  } catch {
    /* 静默：埋点失败绝不影响业务流程 */
  }
}

/** 立即上报当前缓冲（≤50 条/批）；失败静默丢弃，可 await */
export function flush(): Promise<void> {
  if (timer) {
    clearTimeout(timer)
    timer = null
  }
  if (flushing || !buffer.length) return Promise.resolve()
  flushing = true
  return new Promise<void>((resolve) => {
    sendLoop(resolve)
  })
}

/** 逐批发送直到缓冲清空；网络失败即停止本轮（剩余留待下次触发） */
function sendLoop(done: () => void): void {
  if (!buffer.length) {
    flushing = false
    done()
    return
  }
  const events = buffer.splice(0, MAX_BATCH)
  const token = getToken()
  const payload: TrackIn = {
    platform: PLATFORM,
    device_id: getDeviceId(),
    events,
  }
  try {
    uni.request({
      url: `${BASE_URL}/api/track`,
      method: 'POST',
      data: payload,
      header: token ? { Authorization: `Bearer ${token}` } : {},
      success: () => sendLoop(done),
      fail: () => {
        // 丢弃已取出的批次，停止本轮，避免阻塞/无限重试
        flushing = false
        done()
      },
    })
  } catch {
    flushing = false
    done()
  }
}