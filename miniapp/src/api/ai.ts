/**
 * ai API · AI 对话 / 次数 / 饭点决策推荐
 */
import type { AiChatIn, AiChatData, AiTimesData, AiRecommendIn, AiRecommendData } from '@/types/api'
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
