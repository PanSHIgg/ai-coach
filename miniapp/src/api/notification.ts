/**
 * notification API · 提醒订阅（P0「提醒订阅」/ §2.3.1）
 *
 * 契约：backend/app/api/v1/endpoints/notification.py
 *   GET  /api/subscription          我的订阅设置（SubscriptionData）
 *   POST /api/subscription          订阅提醒（SubscriptionIn.template_type → SubscriptionOut）
 *   （另有 POST /api/subscription/cancel，本期入口未使用，未封装）
 *
 * template_type：1午餐提醒 2晚餐提醒 3深夜防崩塌 4称重提醒（后端 schema 口径）。
 */
import type { SubscriptionData, SubscriptionOut, SubscriptionTemplateType } from '@/types/api'
import { request } from './request'

/** 我的订阅设置（各模板类型 → 订阅状态）；silent=true 时失败不弹 toast（后台静默拉取用） */
export function getSubscriptions(silent = false) {
  return request<SubscriptionData>('/api/subscription', { silent })
}

/** 订阅提醒（后端幂等 upsert，保存用户偏好） */
export function subscribeReminder(templateType: SubscriptionTemplateType) {
  return request<SubscriptionOut>('/api/subscription', {
    method: 'POST',
    data: { template_type: templateType },
  })
}