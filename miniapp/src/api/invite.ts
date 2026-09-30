/**
 * invite API · 邀请裂变（CD-05）
 *
 * 契约：contracts/openapi.yaml
 *   POST /api/invite            创建邀请/绑定（InviteIn.invite_code，缺省=创建我的邀请码）
 *   GET  /api/invite/progress   邀请进度与权益
 *
 * 【假设】分享链路传 inviter_id（数字），绑定按后端口径换算为邀请码 `INV-{inviter_id}`
 *         （backend community.py _invite_code/_parse_inviter 的确定性码格式）。
 */
import type { InviteData, InviteProgressData } from '@/types/api'
import { request } from './request'

/** 邀请进度（有效邀请数 / 当前档位 / 下一档奖励 / 海报） */
export function getInviteProgress() {
  return request<InviteProgressData>('/api/invite/progress')
}

/**
 * 绑定邀请关系（被邀请人侧调用；silent：已绑定/无效码等失败不弹 toast）
 */
export function bindInvite(inviterId: number) {
  return request<InviteData>('/api/invite', {
    method: 'POST',
    data: { invite_code: `INV-${inviterId}` },
    silent: true,
  })
}
