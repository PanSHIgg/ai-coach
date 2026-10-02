/**
 * ai API · AI 对话 / 次数 / 饭点决策推荐 / 语音转文字
 */
import type {
  AiChatIn,
  AiChatData,
  AiTimesData,
  AiRecommendIn,
  AiRecommendData,
  VoiceTranscribeIn,
  VoiceTranscribeData,
} from '@/types/api'
import { request } from './request'

/** AI 对话（扣次数；4001=今日次数已用完） */
export function chat(data: AiChatIn) {
  return request<AiChatData>('/api/ai/chat', { method: 'POST', data })
}

/** 今日剩余 AI 次数 */
export function getTimes() {
  return request<AiTimesData>('/api/ai/times')
}

/** 饭点决策：菜单推荐（绿/黄/红健康等级） */
export function recommend(data: AiRecommendIn) {
  return request<AiRecommendData>('/api/ai/recommend', { method: 'POST', data })
}

/**
 * 语音转文字（G4）：audio_base64 为录音文件 base64，format 取 mp3/wav/aac。
 * 无 ASR 配置时后端降级返回空/占位文本（VoiceTranscribeData.provider 标识）。
 */
export function transcribeVoice(payload: VoiceTranscribeIn) {
  return request<VoiceTranscribeData>('/api/ai/voice-transcribe', { method: 'POST', data: payload })
}
