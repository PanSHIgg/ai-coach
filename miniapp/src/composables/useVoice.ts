/**
 * useVoice · 语音输入组合式封装（G4）
 *
 * 链路（小程序端 mp-weixin）：
 *   uni.getRecorderManager() 录音 → onStop 拿到临时音频文件 → FileSystemManager 读为 base64
 *   → POST /api/ai/voice-transcribe（api/ai.transcribeVoice）→ onResult(文本)
 *
 * 降级（H5 / App 等非小程序端）：
 *   条件编译置 SUPPORT_RECORD=false，start() 直接回调提示「当前环境暂不支持语音，请手动输入」，
 *   不调用任何录音 API，不抛错不崩溃（uni-app H5 录音能力有限）。
 *
 * 异常恢复（**任一支路都必须给用户可见反馈，禁止静默**）：
 *   - 权限拒绝 / 用户取消：RecorderManager.onError → 复位录音态并提示，可再次点击重试；
 *   - 无网络 / 转写失败：catch 转写异常 → 提示「语音识别失败，请重试或手动输入」；
 *   - **后端未接 ASR（provider="disabled"、text=""）**：`voice_service.py` 当前是无条件降级 stub，
 *     故空文本要说「语音录入暂未支持」而不是「没听清」——文案不许把未实现的功能说成用户没说清；
 *   - 有 ASR 但没识别出内容（provider 非降级标识、text 为空）：提示「没听清，请重试或手动输入」；
 *   - 上述失败同时把 `status`/`notice` 落到可预期值：`notice` 已被两个调用方接成**常驻提示**
 *     （pages/eat.vue 的 `eat__entry-notice`、pages/record/sport-add.vue 的 `voiceHint`），
 *     用户不用在 1.5s 的 toast 里猜结果；`status` 供调用方按态渲染（当前两页只用
 *     recording/transcribing，保留给后续按态禁用入口的改动）；
 *     `recording` 在 onStop 回调入口即复位，录音到最长时长自动停止时
 *     界面也不会卡在「录音中…点击结束」。
 */
import { ref } from 'vue'
import { transcribeVoice } from '@/api/ai'
import { useToast } from '@/composables/useToast'

/** 录音停止回调结果（RecorderManager.onStop，最小用到字段） */
interface RecorderStopResult {
  tempFilePath?: string
  duration?: number
  fileSize?: number
}

/** 是否支持真实录音：仅微信小程序置 true（条件编译，其余端保持默认 false 优雅降级） */
let SUPPORT_RECORD = false
// #ifdef MP-WEIXIN
SUPPORT_RECORD = typeof uni.getRecorderManager === 'function'
// #endif

/** 传给 voice-transcribe 的音频格式（对齐 VoiceTranscribeIn.format） */
const AUDIO_FORMAT = 'mp3'

/**
 * 后端降级 provider 标识（`app/services/voice_service.py` 的 `DISABLED_PROVIDER`）：
 * 表示「未配置 ASR、功能未启用」，与「用户没说清」是两件事，文案必须分开。
 */
const DISABLED_PROVIDER = 'disabled'

/** 语音链路状态机（idle → recording → transcribing → idle/empty/unsupported/error） */
export type VoiceStatus = 'idle' | 'recording' | 'transcribing' | 'empty' | 'unsupported' | 'error'

export interface UseVoiceOptions {
  /** 转写文本就绪回调（由调用方决定回填到哪个输入框 / 状态） */
  onResult: (text: string) => void
  /** 自定义提示（缺省走 toast.info）；无论是否自定义，`notice` 都会写入同一条文案 */
  onTip?: (message: string) => void
  /** 单次最长录音时长 ms，默认 30s（控制 base64 体积，避免请求体过大） */
  maxDuration?: number
}

export function useVoice(options: UseVoiceOptions) {
  const toast = useToast()
  const recording = ref(false)
  const transcribing = ref(false)
  /** 链路状态：调用方据此渲染按钮文案 / 常驻提示，不靠瞬时 toast 猜结果 */
  const status = ref<VoiceStatus>('idle')
  /** 最近一次面向用户的提示（空串=无提示）；供页面放在按钮下方常驻显示 */
  const notice = ref('')

  let recorder: ReturnType<typeof uni.getRecorderManager> | null = null
  // 页面卸载后忽略迟到的录音 / 转写回调，避免在已销毁页面上 setState
  let disposed = false

  function tip(message: string, next: VoiceStatus = 'idle') {
    notice.value = message
    status.value = next
    if (options.onTip) options.onTip(message)
    else toast.info({ title: message })
  }

  function ensureRecorder() {
    if (!recorder) {
      recorder = uni.getRecorderManager()
      recorder.onStop((res: RecorderStopResult) => {
        void handleStop(res)
      })
      recorder.onError(() => {
        recording.value = false
        tip('录音失败，请检查麦克风权限后重试，或手动输入', 'error')
      })
    }
    return recorder
  }

  /** 开始录音（环境不支持时直接降级提示，不抛错） */
  function start() {
    if (disposed) return
    if (!SUPPORT_RECORD) {
      tip('当前环境暂不支持语音，请手动输入', 'unsupported')
      return
    }
    if (recording.value || transcribing.value) return
    try {
      const mgr = ensureRecorder()
      // 16k/单声道/32kbps/mp3：微信 RecorderManager 支持的合法组合
      mgr.start({
        duration: options.maxDuration ?? 30000,
        sampleRate: 16000,
        numberOfChannels: 1,
        encodeBitRate: 32000,
        format: AUDIO_FORMAT,
      })
      recording.value = true
      status.value = 'recording'
      notice.value = ''
    } catch (e) {
      recording.value = false
      tip('录音启动失败，请手动输入', 'error')
    }
  }

  /** 停止录音并触发转写（onStop 回调里异步处理） */
  function stop() {
    if (!recording.value) return
    recording.value = false
    try {
      recorder?.stop()
    } catch (e) {
      status.value = 'idle'
      tip('录音结束异常，请手动输入', 'error')
    }
  }

  /** 切换录音态：点击开始 / 再点结束 */
  function toggle() {
    if (recording.value) stop()
    else start()
  }

  /** 读取录音临时文件为 base64（小程序 FileSystemManager） */
  function readBase64(filePath: string): Promise<string> {
    return new Promise((resolve, reject) => {
      uni.getFileSystemManager().readFile({
        filePath,
        encoding: 'base64',
        success: (res) => {
          resolve(typeof res.data === 'string' ? res.data : '')
        },
        fail: (err) => {
          reject(new Error((err as { errMsg?: string }).errMsg || '读取录音失败'))
        },
      })
    })
  }

  async function handleStop(res: RecorderStopResult) {
    if (disposed) return
    // 到达 maxDuration 由录音器自动停止时不会走 stop()，这里必须复位，否则界面卡在「录音中」
    recording.value = false
    const filePath = res?.tempFilePath
    if (!filePath) {
      tip('没有录到声音，请重试或手动输入', 'empty')
      return
    }
    transcribing.value = true
    status.value = 'transcribing'
    try {
      const audioBase64 = await readBase64(filePath)
      if (!audioBase64) {
        tip('没有录到声音，请重试或手动输入', 'empty')
        return
      }
      const data = await transcribeVoice({ audio_base64: audioBase64, format: AUDIO_FORMAT })
      const text = (data?.text ?? '').trim()
      if (!text) {
        // 空文本一律明确反馈（旧实现只有一句「没听清」，把「后端未实现」说成「用户没说清」）
        const provider = (data?.provider ?? '').toLowerCase()
        if (provider === DISABLED_PROVIDER) {
          tip('语音录入暂未支持，请手动输入', 'unsupported')
        } else {
          tip('没听清，请重试或手动输入', 'empty')
        }
        return
      }
      notice.value = ''
      status.value = 'idle'
      options.onResult(text)
    } catch (e) {
      tip((e as Error).message || '语音识别失败，请重试或手动输入', 'error')
    } finally {
      transcribing.value = false
      // 仍处在 transcribing 说明成功路径已把状态收敛到 idle/empty/error，这里只兜底复位
      if (status.value === 'transcribing') status.value = 'idle'
    }
  }

  /** 页面卸载时调用：停止录音并忽略后续回调 */
  function dispose() {
    disposed = true
    if (recording.value) {
      try {
        recorder?.stop()
      } catch (e) {
        // 卸载阶段无需再提示
      }
    }
    recording.value = false
    transcribing.value = false
    status.value = 'idle'
  }

  return {
    supported: SUPPORT_RECORD,
    recording,
    transcribing,
    status,
    notice,
    start,
    stop,
    toggle,
    dispose,
  }
}