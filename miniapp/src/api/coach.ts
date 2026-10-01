/**
 * coach API · 真人教练工单 / 专家问诊（G1）
 *
 * 契约：contracts/openapi.yaml（类型见 src/types/api.d.ts）
 *   POST /api/coach/ticket                提问/问诊下单（question 作为首条消息落库，扣真人次数；4001=次数耗尽）
 *   GET  /api/coach/tickets               我的工单列表（status/page/page_size）
 *   GET  /api/coach/ticket/{id}           工单详情（含消息流，按 created_at ASC）
 *   POST /api/coach/ticket/{id}/message   追加描述
 *
 * 交互形态为**异步工单消息**（非实时对话）：用户提问后由教练异步回复，
 * 前端靠「进页面 / 发送后 / 手动刷新」拉取详情拿新消息，不做轮询与长连接。
 */
import type {
  CoachTicketIn,
  CoachTicketCreatedData,
  CoachTicketPageData,
  CoachTicketDetailData,
  CoachMessageIn,
  CoachMessageData,
} from '@/types/api'
import { request } from './request'

/** 提问 / 建单（返回 ticket_id；首条消息即 question） */
export function createCoachTicket(data: CoachTicketIn) {
  return request<CoachTicketCreatedData>('/api/coach/ticket', { method: 'POST', data })
}

/** 我的工单列表（status：1待回复 2已回复 3已关闭；created_at DESC） */
export function getCoachTickets(params?: {
  status?: 1 | 2 | 3
  page?: number
  page_size?: number
}) {
  return request<CoachTicketPageData>('/api/coach/tickets', { data: params })
}

/** 工单详情（含消息流）；非本人 → 3001 */
export function getCoachTicket(id: number) {
  return request<CoachTicketDetailData>(`/api/coach/ticket/${id}`)
}

/** 追加描述（1-2000 字） */
export function addCoachTicketMessage(id: number, data: CoachMessageIn) {
  return request<CoachMessageData>(`/api/coach/ticket/${id}/message`, { method: 'POST', data })
}
