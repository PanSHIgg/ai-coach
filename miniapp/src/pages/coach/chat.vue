<template>
  <view class="coach">
    <!-- 未登录：无权限态（§5.8） -->
    <CNoPermission v-if="!userStore.isLogined" @action="goLogin" />

    <!-- 未订阅 / 无真人次数：灰显预览 + 浮层「该功能需进阶版」（§5.8） -->
    <CNoBenefit
      v-else-if="locked"
      :text="lockText"
      button-text="立即开通"
      @action="goPlan"
    >
      <view class="coach__preview">
        <view class="msg msg--coach">
          <image class="msg__avatar" src="/static/icons/ic-gym.png" mode="aspectFit" />
          <view class="msg__bubble">
            <text class="msg__text">真人教练会在这里回复你的饮食与训练问题</text>
          </view>
        </view>
        <view class="msg msg--user">
          <image class="msg__avatar" src="/static/icons/ic-user.png" mode="aspectFit" />
          <view class="msg__bubble">
            <text class="msg__text">这个菜油多吗？晚餐怎么吃不超标？</text>
          </view>
        </view>
        <CInput class="coach__preview-input" disabled placeholder="订阅进阶版后可向真人教练提问" />
      </view>
    </CNoBenefit>

    <template v-else>
      <!-- 工单概要：标题 + 状态 + 历史工单入口 -->
      <view class="coach__head">
        <view class="coach__head-main">
          <text class="coach__title">{{ ticketTitle }}</text>
          <text class="coach__status">{{ ticketStatusText }}</text>
        </view>
        <text class="coach__link" @tap="goTickets">历史问诊 ›</text>
      </view>

      <!-- 消息流 -->
      <scroll-view class="coach__body" scroll-y :scroll-into-view="anchorId" scroll-with-animation>
        <view class="coach__inner">
          <CSkeleton v-if="loading && !messages.length" type="card" />
          <CError v-else-if="error && !messages.length" @retry="loadDetail" />
          <CEmpty
            v-else-if="!messages.length"
            icon="empty-chat"
            text="描述你的问题，真人教练会尽快回复"
            button-text=""
          />

          <view
            v-for="(m, i) in messages"
            :id="`msg-${i}`"
            :key="m.id"
            class="msg"
            :class="m.role === 'user' ? 'msg--user' : 'msg--coach'"
          >
            <image
              class="msg__avatar"
              :src="m.role === 'user' ? '/static/icons/ic-user.png' : '/static/icons/ic-gym.png'"
              mode="aspectFit"
            />
            <view class="msg__bubble">
              <text class="msg__text" :class="{ 'msg__text--error': m.error }">{{ m.text }}</text>
              <text class="msg__time">{{ m.time }}{{ m.pending ? ' · 发送中' : '' }}</text>
            </view>
          </view>
        </view>
      </scroll-view>

      <!-- 底部输入区 -->
      <view class="coach__foot">
        <view class="quota">
          <text class="quota__text">{{ quotaText }}</text>
          <text class="quota__link" @tap="refresh">刷新 ›</text>
        </view>
        <view class="coach__input">
          <CInput
            v-model="draft"
            class="coach__input-box"
            :maxlength="CONTENT_MAX"
            :placeholder="ticketId === null ? '描述你的问题，提交给真人教练…' : '补充描述…'"
            @confirm="onSend"
          />
          <CButton class="coach__send" size="md" :disabled="!canSend" :loading="sending" @click="onSend">
            发送
          </CButton>
        </view>
      </view>
    </template>
  </view>
</template>

<script setup lang="ts">
/**
 * FE · 专家问诊（真人教练工单对话）— G1
 * 依据：docs/split/03-页面布局与交互说明.md §5.2-8「[立即咨询] → 真人教练对话 / 教练工单服务」
 *       §5.8「未开通权益：页面内容灰显预览 + 浮层『该功能需进阶版』[立即开通] → 订阅页」
 * 契约：POST /api/coach/ticket、GET /api/coach/tickets、GET /api/coach/ticket/{id}、
 *       POST /api/coach/ticket/{id}/message、GET /api/plan/benefit
 *
 * 【假设】① 交互为异步工单消息：不做实时推送，靠「进页面 / 发送后 / 点击刷新」拉详情拿新回复；
 *         ② 进入时自动续接最近一条未关闭工单（GET /api/coach/tickets page_size=1），
 *            无工单时首条发送即建单（question 作为首条消息）；
 *         ③ 权益判定用 /api/plan/benefit 的 coach_times_left：为 0 即锁定（不区分未订阅与次数用尽）。
 */
import { computed, nextTick, ref } from 'vue'
import { onLoad, onShow } from '@dcloudio/uni-app'
import { useUserStore } from '@/stores/user'
import { useToast } from '@/composables/useToast'
import { redirectToLogin } from '@/utils/nav'
import { track } from '@/utils/track'
import {
  createCoachTicket,
  getCoachTickets,
  getCoachTicket,
  addCoachTicketMessage,
} from '@/api/coach'
import { getPlanBenefit } from '@/api/plan'
import type { CoachTicketItem, CoachTicketMessageItem } from '@/types/api'

/** 工单状态文案（CoachTicketStatus：1待回复 2已回复 3已关闭） */
const STATUS_TEXT: Record<number, string> = { 1: '待教练回复', 2: '教练已回复', 3: '已关闭' }
/** 单次输入上限：契约 question 1-500 / content 1-2000，取小者统一前端上限 */
const CONTENT_MAX = 500

/** 页面内消息（服务端消息 + 本地乐观消息） */
interface MsgItem {
  /** 服务端消息 id；本地乐观消息为负数 */
  id: number
  role: 'user' | 'coach'
  text: string
  time: string
  /** 本地乐观消息：请求进行中 */
  pending?: boolean
  /** 发送失败 */
  error?: boolean
}

const userStore = useUserStore()
const toast = useToast()

/** 当前工单 id；null=尚未建单 */
const ticketId = ref<number | null>(null)
const ticket = ref<CoachTicketItem | null>(null)
const messages = ref<MsgItem[]>([])
const draft = ref('')
const sending = ref(false)
const loading = ref(false)
const error = ref(false)

/** 真人问诊剩余次数：null=拉取失败（不据此锁死入口） */
const coachTimesLeft = ref<number | null>(null)
const tier = ref<0 | 1 | 2 | 3>(0)
const benefitLoaded = ref(false)

/** scroll-view 锚点：滚到最后一条 */
const anchorId = ref('')

/** 无真人次数 → 灰显 + 浮层引导订阅 */
const locked = computed(() => benefitLoaded.value && coachTimesLeft.value === 0)
const lockText = computed(() =>
  tier.value === 0 ? '该功能需进阶版' : '真人问诊次数已用完，续费或升级解锁',
)

const ticketTitle = computed(() =>
  ticketId.value === null ? '新的问诊' : ticket.value?.title || `问诊 #${ticketId.value}`,
)
const ticketStatusText = computed(() =>
  ticketId.value === null ? '提交后教练将收到' : STATUS_TEXT[ticket.value?.status || 1] || '',
)

const quotaText = computed(() => {
  if (!benefitLoaded.value) return '权益加载中…'
  if (coachTimesLeft.value === null) return '权益暂不可用'
  if (coachTimesLeft.value < 0) return '真人问诊不限次'
  return `剩余真人问诊 ${coachTimesLeft.value} 次`
})

const canSend = computed(() => !sending.value && !!draft.value.trim())

/** 时间展示：ISO → MM-DD HH:mm（解析失败回退原串） */
function fmtTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

function nowText(): string {
  return fmtTime(new Date().toISOString())
}

function toMsg(m: CoachTicketMessageItem): MsgItem {
  return {
    id: m.id,
    role: m.sender_role === 2 ? 'coach' : 'user',
    text: m.content,
    time: fmtTime(m.created_at),
  }
}

function scrollToBottom() {
  nextTick(() => {
    anchorId.value = messages.value.length ? `msg-${messages.value.length - 1}` : ''
  })
}

/* ---------- 数据加载 ---------- */

async function loadBenefit() {
  try {
    const data = await getPlanBenefit()
    tier.value = (data?.tier ?? 0) as 0 | 1 | 2 | 3
    coachTimesLeft.value = data?.coach_times_left ?? 0
  } catch (e) {
    // request 已 toast；保留 null，避免网络抖动误锁入口
    coachTimesLeft.value = null
    void e
  } finally {
    benefitLoaded.value = true
  }
}

async function loadDetail() {
  const id = ticketId.value
  if (id === null) {
    messages.value = []
    return
  }
  loading.value = true
  error.value = false
  try {
    const data = await getCoachTicket(id)
    ticket.value = data?.ticket ?? null
    messages.value = (data?.messages ?? []).map(toMsg)
  } catch (e) {
    error.value = true
    void e
  } finally {
    loading.value = false
    scrollToBottom()
  }
}

/** 无指定工单时，续接最近一条工单 */
async function loadLatestTicket() {
  try {
    const data = await getCoachTickets({ page: 1, page_size: 1 })
    const first = data?.items?.[0]
    ticketId.value = first ? first.id : null
  } catch (e) {
    ticketId.value = null
    void e
  }
}

/** 进页面 / 手动刷新：拉权益 → 拉（或续接）工单详情 */
async function boot() {
  await loadBenefit()
  if (locked.value) return
  if (ticketId.value === null) await loadLatestTicket()
  await loadDetail()
}

function refresh() {
  if (sending.value) return
  void boot()
}

/* ---------- 发送 ---------- */

async function onSend() {
  if (!canSend.value) return
  const text = draft.value.trim()
  if (!text) return

  draft.value = ''
  // 乐观插入：服务端返回后由 loadDetail 用真实消息流覆盖
  messages.value = [
    ...messages.value,
    { id: -Date.now(), role: 'user', text, time: nowText(), pending: true },
  ]
  scrollToBottom()
  sending.value = true
  try {
    if (ticketId.value === null) {
      const created = await createCoachTicket({ question: text })
      ticketId.value = created?.ticket_id ?? null
      // 建单即扣次数，同步一次权益
      await loadBenefit()
      track('coach_ticket_create', { ticket_id: created?.ticket_id ?? 0 })
      toast.success({ title: '已提交，教练会尽快回复' })
    } else {
      await addCoachTicketMessage(ticketId.value, { content: text })
      track('coach_message', { ticket_id: ticketId.value })
    }
    await loadDetail()
  } catch (e) {
    // request 已 toast；把乐观消息标记为失败态，避免「发出去了但没回显」
    messages.value = messages.value.map((m) =>
      m.pending ? { ...m, pending: false, error: true } : m,
    )
    void e
  } finally {
    sending.value = false
  }
}

/* ---------- 跳转 ---------- */

function goLogin() {
  redirectToLogin()
}
function goPlan() {
  uni.navigateTo({ url: '/pages/plan/index' })
}
function goTickets() {
  uni.navigateTo({ url: '/pages/coach/tickets' })
}

/* ---------- 生命周期 ---------- */

onLoad((options) => {
  const id = Number((options as { id?: string } | undefined)?.id)
  if (Number.isFinite(id) && id > 0) ticketId.value = id
})

onShow(() => {
  if (!userStore.isLogined) {
    redirectToLogin()
    return
  }
  void boot()
})
</script>

<style lang="scss" scoped>
.coach {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: $bg;

  &__head {
    @include flex-between;

    padding: $space-sm $space-md;
    background: $card;
    border-bottom: 1rpx solid $border;
  }

  &__head-main {
    flex: 1;
    min-width: 0;
  }

  &__title {
    display: block;
    font-size: $t-26;
    font-weight: 500;
    color: $text-1;
    @include ellipsis;
  }

  &__status {
    font-size: $t-22;
    color: $text-3;
  }

  &__link {
    flex: none;
    margin-left: $space-sm;
    font-size: $t-22;
    color: $brand;
  }

  &__body {
    flex: 1;
    overflow: hidden;
  }

  &__inner {
    padding: $space-md;
  }

  &__foot {
    padding: $space-sm $space-md 0;
    background: $card;
    border-top: 1rpx solid $border;
    @include safe-area-bottom($space-sm);
  }

  &__input {
    display: flex;
    align-items: center;
    gap: $space-sm;
    padding-bottom: $space-sm;
  }

  &__input-box {
    flex: 1;
  }

  &__send {
    flex-shrink: 0;
  }

  // 未解锁权益时的灰显预览（CNoBenefit 内部再加灰度 + 蒙层）
  &__preview {
    padding: $space-md;
  }

  &__preview-input {
    margin-top: $space-md;
  }
}

.msg {
  display: flex;
  margin-bottom: $space-md;

  &__avatar {
    flex-shrink: 0;
    width: 64rpx;
    height: 64rpx;
    margin-right: $space-sm;
    padding: 12rpx;
    background: #f0fdf4;
    border-radius: 50%;
    box-sizing: border-box;
  }

  &__bubble {
    max-width: 560rpx;
    padding: $space-sm $space-md;
    background: $card;
    border-radius: $radius;
    box-shadow: $shadow;
  }

  &__text {
    display: block;
    font-size: $t-26;
    line-height: 1.6;
    color: $text-1;

    &--error {
      color: $warn;
    }
  }

  &__time {
    display: block;
    margin-top: $space-xs;
    font-size: $t-22;
    color: $text-3;
  }

  // 用户消息：右对齐、气泡品牌色
  &--user {
    flex-direction: row-reverse;

    .msg__avatar {
      margin-right: 0;
      margin-left: $space-sm;
    }

    .msg__bubble {
      background: $brand;
    }

    .msg__text {
      color: var(--card);
    }

    .msg__time {
      color: rgba(255, 255, 255, 0.75);
    }
  }
}

.quota {
  @include flex-between;

  padding: $space-xs 0;

  &__text {
    font-size: $t-22;
    color: $text-3;
  }

  &__link {
    font-size: $t-22;
    color: $brand;
  }
}
</style>
