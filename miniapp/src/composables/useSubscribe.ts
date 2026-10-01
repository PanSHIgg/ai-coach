/**
 * useSubscribe · 提醒订阅授权（P0「提醒订阅」/ §2.3.1 餐前·深夜推送 / §2.4 异常场景）
 *
 * 流程：
 *   1. uni.requestSubscribeMessage({ tmplIds }) 申请一次性订阅消息授权（一次申请全部提醒模板）
 *   2. 用户同意 → 调后端 POST /api/subscription 保存订阅偏好（按 template_type）
 *   3. 被拒 / 已拒绝 / 调用失败 → uni.showModal 引导「去设置」→ uni.openSetting()，仅引导不改偏好
 *   4. 任一分支都不阻断核心流程：requestSubscribe 始终 resolve，不抛出、不阻塞调用方（§2.4）
 *
 * 【假设】微信订阅消息模板 ID 未知（须在微信公众平台-功能-订阅消息申请后配置），
 *         此处从环境配置 VITE_WX_TMPL_{template_type} 读取；未配置时回退占位常量（非真实 ID）。
 */
import type { SubscriptionTemplateType } from '@/types/api'
import { subscribeReminder } from '@/api/notification'
import { useToast } from './useToast'

/** 【假设】模板 ID 占位符：真值需在微信公众平台申请后经环境配置注入，禁止硬编码真实 ID。 */
export const TMPL_ID_PLACEHOLDER = 'TMPL_ID_PLACEHOLDER'

/** 提醒模板清单（与后端 template_type 口径一致：1午餐 2晚餐 3深夜 4称重） */
export const SUBSCRIBE_TEMPLATES: { type: SubscriptionTemplateType; name: string }[] = [
  { type: 1, name: '午餐提醒' },
  { type: 2, name: '晚餐提醒' },
  { type: 3, name: '深夜提醒' },
  { type: 4, name: '称重提醒' },
]

/** 【假设】模板 ID 从环境配置读取（VITE_WX_TMPL_{template_type}），缺省回退占位符。 */
function getTmplId(type: SubscriptionTemplateType): string {
  const env = import.meta.env as unknown as Record<string, string | undefined>
  return env[`VITE_WX_TMPL_${type}`] || TMPL_ID_PLACEHOLDER
}

export function useSubscribe() {
  const toast = useToast()

  /** 未授权（被拒/已拒绝/调用失败）→ 引导跳转设置页；不阻断任何核心流程 */
  function guideToSetting() {
    uni.showModal({
      title: '开启提醒',
      content: '订阅消息未开启，将无法收到餐前与深夜提醒。是否前往设置开启？',
      confirmText: '去设置',
      cancelText: '暂不',
      success: (res) => {
        if (res.confirm) uni.openSetting({})
      },
    })
  }

  /**
   * 申请订阅授权并保存偏好（一次申请全部提醒模板）。
   * 始终 resolve（true=至少一条授权成功），被拒时引导设置页，均不阻断核心流程。
   */
  function requestSubscribe(): Promise<boolean> {
    const tmplIds = SUBSCRIBE_TEMPLATES.map((t) => getTmplId(t.type))
    return new Promise((resolve) => {
      uni.requestSubscribeMessage({
        tmplIds,
        success: (res) => {
          const result = res as unknown as Record<string, string>
          const accepted = SUBSCRIBE_TEMPLATES.filter((t) => result[getTmplId(t.type)] === 'accept')
          if (accepted.length === SUBSCRIBE_TEMPLATES.length) {
            // 全部同意 → 保存订阅偏好（后端失败不阻断，仅静默）
            Promise.allSettled(accepted.map((t) => subscribeReminder(t.type))).then((rs) => {
              if (rs.some((r) => r.status === 'fulfilled')) toast.success({ title: '已开启提醒' })
            })
          } else if (accepted.length > 0) {
            // 部分同意 → 保存已授权项 + 引导开启其余
            accepted.forEach((t) => subscribeReminder(t.type).catch(() => {}))
            guideToSetting()
          } else {
            // 全部被拒/已拒绝 → 引导设置页，不阻断
            guideToSetting()
          }
          resolve(accepted.length > 0)
        },
        fail: () => {
          // 调用失败（模板 ID 未配置 / 系统拒绝 20004·20005 等）→ 引导设置页，不阻断
          guideToSetting()
          resolve(false)
        },
      })
    })
  }

  return { requestSubscribe }
}