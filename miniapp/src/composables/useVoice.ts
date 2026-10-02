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
 * 异常恢复：
 *   - 权限拒绝 / 用户取消：RecorderManager.onError → 复位录音态并提示，可再次点击重试；
 *   - 无网络 / 转写失败：catch 转写异常 → 提示「语音识别失败，请重试或手动输入」；
 *   - 空音频 / 空文本：提示「没听清，请重试或手动输入」。
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

export interface UseVoiceOptions {
  /** 转写文本就绪回调（由调用方决定回填到哪个输入框 / 状态） */
  onResult: (text: string) => void
  /** 自定义提示（缺省走 toast.info） */
  onTip?: (message: string) => void
  /** 单次最长录音时长 ms，默认 30s（控制 base64 体积，避免请求体过大） */
  maxDuration?: number
}

export function useVoice(options: UseVoiceOptions) {
  const toast = useToast()
  const recording = ref(false)
  const transcribing = ref(false)

  let recorder: ReturnType<typeof uni.getRecorderManager> | null = null
  // 页面卸载后忽略迟到的录音 / 转写回调，避免在已销毁页面上 setState
  let disposed = false

  function tip(message: string) {
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
        tip('录音失败，请检查麦克风权限后重试，或手动输入')
      })
    }
    return recorder
  }

  /** 开始录音（环境不支持时直接降级提示，不抛错） */
  function start() {
    if (disposed) return
    if (!SUPPORT_RECORD) {
      tip('当前环境暂不支持语音，请手动输入')
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
    } catch (e) {
      recording.value = false
      tip('录音启动失败，请手动输入')
    }
  }

  /** 停止录音并触发转写（onStop 回调里异步处理） */
  function stop() {
    if (!recording.value) return
    recording.value = false
    try {
      recorder?.stop()
    } catch (e) {
      tip('录音结束异常，请手动输入')
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
    const filePath = res?.tempFilePath
    if (!filePath) {
      tip('没有录到声音，请重试或手动输入')
      return
    }
    transcribing.value = true
    try {
      const audioBase64 = await readBase64(filePath)
      if (!audioBase64) {
        tip('没有录到声音，请重试或手动输入')
        return
      }
      const data = await transcribeVoice({ audio_base64: audioBase64, format: AUDIO_FORMAT })
      const text = (data?.text ?? '').trim()
      if (!text) {
        // 无 ASR 配置时后端走降级，可能返回空文本
        tip('没听清，请重试或手动输入')
        return
      }
      options.onResult(text)
    } catch (e) {
      tip((e as Error).message || '语音识别失败，请重试或手动输入')
    } finally {
      transcribing.value = false
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
  }

  return { supported: SUPPORT_RECORD, recording, transcribing, start, stop, toggle, dispose }
}