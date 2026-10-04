/**
 * community API · 社区五种社交（Phase 4 / FE5）
 *
 * 契约：contracts/openapi.yaml /api/community/*（统一 envelope；request 已解包 data）。
 */
import type {
  BattleCreateIn,
  BattleItem,
  BattleJoinData,
  BattlePageData,
  BattleQuitData,
  ChallengeItem,
  ChallengeJoinData,
  ChallengeLeaderboardData,
  ChallengePageData,
  CommentPageData,
  CommunityCommentIn,
  CommunityCommentOut,
  CommunityPostCreated,
  CommunityPostIn,
  CommunityPostOut,
  ExperiencePageData,
  GroupCheckinData,
  GroupItem,
  GroupJoinData,
  GroupPageData,
  LeaderboardData,
  LikeData,
  PostDeleteData,
  PostPageData,
  SuperviseOut,
  SuperviseRecordsData,
  SuperviseRemindData,
} from '@/types/api'
import { request } from './request'

/**
 * 小程序运行时没有浏览器那套查询串参数构造（实测同步抛 ReferenceError），
 * 这里手工拼接查询串，语义与原实现完全等价：
 * - falsy（undefined/null/''/0/NaN/false）参数一律跳过（对齐原 `if (params.x)` 真值判断）
 * - 参数顺序由调用处数组顺序决定，与原实现的插入顺序一致
 * - 键/值均用 encodeURIComponent 编码（小程序可用）
 */
function buildQuery(fields: Array<[string, string | number | undefined | null]>): string {
  const parts: string[] = []
  for (const [key, value] of fields) {
    if (!value) continue
    parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`)
  }
  return parts.join('&')
}

/* ---------- 动态 ---------- */

export function listPosts(params: { page?: number; page_size?: number; post_type?: 1 | 2 | 3 } = {}) {
  const qs = buildQuery([
    ['page', params.page],
    ['page_size', params.page_size],
    ['post_type', params.post_type],
  ])
  return request<PostPageData>(`/api/community/post/list${qs ? `?${qs}` : ''}`)
}

export function createPost(data: CommunityPostIn) {
  return request<CommunityPostCreated>('/api/community/post', { method: 'POST', data })
}

export function getPost(id: number) {
  return request<CommunityPostOut>(`/api/community/post/${id}`)
}

export function deletePost(id: number) {
  return request<PostDeleteData>(`/api/community/post/${id}`, { method: 'DELETE' })
}

export function likePost(id: number) {
  return request<LikeData>(`/api/community/post/${id}/like`, { method: 'POST' })
}

export function unlikePost(id: number) {
  return request<LikeData>(`/api/community/post/${id}/like`, { method: 'DELETE' })
}

export function listComments(postId: number, params: { page?: number; page_size?: number } = {}) {
  const qs = buildQuery([
    ['page', params.page],
    ['page_size', params.page_size],
  ])
  return request<CommentPageData>(
    `/api/community/post/${postId}/comment/list${qs ? `?${qs}` : ''}`,
  )
}

export function createComment(postId: number, data: CommunityCommentIn) {
  return request<CommunityCommentOut>(`/api/community/post/${postId}/comment`, {
    method: 'POST',
    data,
  })
}

export function listExperience(params: { page?: number; page_size?: number } = {}) {
  const qs = buildQuery([
    ['page', params.page],
    ['page_size', params.page_size],
  ])
  return request<ExperiencePageData>(`/api/community/experience/list${qs ? `?${qs}` : ''}`)
}

/* ---------- 监督搭子 ---------- */

export function getSupervise() {
  return request<SuperviseOut>('/api/community/supervise')
}

export function matchSupervise(data: { partner_id?: number | null } = {}) {
  return request<SuperviseOut>('/api/community/supervise/match', { method: 'POST', data })
}

export function remindSupervise(id: number) {
  return request<SuperviseRemindData>(`/api/community/supervise/${id}/remind`, { method: 'POST' })
}

export function superviseRecords(id: number) {
  return request<SuperviseRecordsData>(`/api/community/supervise/${id}/records`)
}

/* ---------- 兴趣社群 ---------- */

export function listGroups(params: { page?: number; page_size?: number } = {}) {
  const qs = buildQuery([
    ['page', params.page],
    ['page_size', params.page_size],
  ])
  return request<GroupPageData>(`/api/community/group/list${qs ? `?${qs}` : ''}`)
}

export function getGroup(id: number) {
  return request<GroupItem>(`/api/community/group/${id}`)
}

export function joinGroup(id: number) {
  return request<GroupJoinData>(`/api/community/group/${id}/join`, { method: 'POST' })
}

export function checkinGroup(id: number) {
  return request<GroupCheckinData>(`/api/community/group/${id}/checkin`, { method: 'POST' })
}

/* ---------- 约战 ---------- */

export function createBattle(data: BattleCreateIn) {
  return request<BattleItem>('/api/community/battle', { method: 'POST', data })
}

export function listBattles(
  params: { city?: string; status?: number; page?: number; page_size?: number } = {},
) {
  const qs = buildQuery([
    ['city', params.city],
    ['status', params.status],
    ['page', params.page],
    ['page_size', params.page_size],
  ])
  return request<BattlePageData>(`/api/community/battle/list${qs ? `?${qs}` : ''}`)
}

export function joinBattle(data: { battle_id: number }) {
  return request<BattleJoinData>('/api/community/battle/join', { method: 'POST', data })
}

/** 退出约战（join_count 为退出后的最新人数；满员退出后回「招募中」） */
export function quitBattle(data: { battle_id: number }) {
  return request<BattleQuitData>('/api/community/battle/quit', { method: 'POST', data })
}

/* ---------- 挑战赛 ---------- */

export function listChallenges(params: { page?: number; page_size?: number } = {}) {
  const qs = buildQuery([
    ['page', params.page],
    ['page_size', params.page_size],
  ])
  return request<ChallengePageData>(`/api/community/challenge/list${qs ? `?${qs}` : ''}`)
}

export function getChallenge(id: number) {
  return request<ChallengeItem>(`/api/community/challenge/${id}`)
}

export function joinChallenge(id: number) {
  return request<ChallengeJoinData>(`/api/community/challenge/${id}/join`, { method: 'POST' })
}

export function challengeLeaderboard(id: number) {
  return request<ChallengeLeaderboardData>(`/api/community/challenge/${id}/leaderboard`)
}

/* ---------- 热量控制榜 ---------- */

export function getLeaderboard(params: { period_type?: number; period_key?: string } = {}) {
  const qs = buildQuery([
    ['period_type', params.period_type],
    ['period_key', params.period_key],
  ])
  return request<LeaderboardData>(`/api/community/leaderboard${qs ? `?${qs}` : ''}`)
}