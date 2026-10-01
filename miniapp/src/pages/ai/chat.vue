<template>
  <view class="chat">
    <!-- 消息列表（§5.1 AI 教练卡 → AI 对话页） -->
    <scroll-view class="chat__body" scroll-y :scroll-into-view="anchorId" scroll-with-animation>
      <view class="chat__inner">
        <CEmpty
          v-if="!messages.length"
          icon="empty-chat"
          text="饿了能吃什么？今天为什么没瘦？问问 AI 教练"
          button-text=""
        />

        <view
          v-for="(m, i) in messages"
          :id="`msg-${i}`"
          :key="i"
          class="msg"
          :class="m.role === 'user' ? 'msg--user' : 'msg--ai'"
        >
          <image
            class="msg__avatar"
            :src="m.role === 'user' ? '/static/icons/ic-user.png' : '/static/icons/ic-robot.png'"
            mode="aspectFit"
          />
          <view class="msg__bubble">
            <text class="msg__text" :class="{ 'msg__text--error': m.error }">{{ m.text }}</text>

            <!-- RAG 引用来源（AiChatData.references） -->
            <view v-if="m.references && m.references.length" class="msg__refs">
              <text v-for="r in m.references" :key="r" class="msg__ref">{{ r }}</text>
            </view>

            <!-- 免责声明（06-AI服务.md §六） -->
            <text v-if="m.role === 'ai'" class="msg__disclaimer">AI 输出仅供参考，具体请遵医嘱</text>

            <!-- AI 满意度评分（§1.6 目标 > 4.5/5；埋点 ai_rating，口径见埋点文档 §2） -->
            <view v-if="m.role === 'ai' && !m.error" class="rate">
              <text class="rate__label">{{ m.score ? '感谢你的评价' : '这个回答有帮助吗？' }}</text>
              <view class="rate__stars">
                <image
                  v-for="s in 5"
                  :key="s"
                  class="rate__star"
                  :src="(m.score || 0) >= s ? '/static/icons/ic-star.png' : '/static/icons/ic-star-gray.png'"
                  mode="aspectFit"
                  @tap="onRate(i, s)"
                />
              </view>
            </view>
          </view>
        </view>
      </view>
    </scroll-view>

    <!-- 底部输入区 -->
    <view class="chat__foot">
      <!-- 快捷问题（空会话时引导；饥饿急救入口也在其中） -->
      <scroll-view v-if="!messages.length" class="chips" scroll-x>
        <view class="chips__inner">
          <text v-for="q in QUICK_QUESTIONS" :key="q" class="chips__item" @tap="onPick(q)">
            {{ q }}
          </text>
          <text class="chips__item chips__item--sos" @tap="openRescue">饥饿急救</text>
        </view>
      </scroll-view>
      <view v-else class="chips chips--single">
        <text class="chips__item chips__item--sos" @tap="openRescue">饥饿急救</text>
      </view>

      <!-- 次数提示（06 §1.5：次数用完时输入框上方展示，无法发送） -->
      <view class="quota" :class="{ 'quota--zero': timesLeft === 0 }">
        <text class="quota__text">{{ quotaText }}</text>
        <text v-if="timesLeft === 0" class="quota__link" @tap="onInvite">邀请好友解锁 ›</text>
      </view>

      <view class="chat__input">
        <CInput
          v-model="draft"
          class="chat__input-box"
          :disabled="!canSend"
          :placeholder="timesLeft === 0 ? '今日次数已用完' : '问问 AI 教练…'"
          @confirm="onSend"
        />
        <CButton
          class="chat__send"
          size="md"
          :disabled="!canSend"
          :loading="sending"
          @click="onSend"
        >
          发送
        </CButton>
      </view>
    </view>

    <!-- 饥饿急救弹窗（预置话术，不发请求也能给建议） -->
    <view v-if="rescueVisible" class="mask" @tap="closeRescue">
      <view class="rescue" @tap.stop>
        <text class="rescue__title">饥饿急救</text>
        <view v-for="(t, i) in RESCUE_TIPS" :key="i" class="rescue__item">
          <text class="rescue__num">{{ i + 1 }}</text>
          <text class="rescue__text">{{ t }}</text>
        </view>
        <text class="rescue__disclaimer">AI 输出仅供参考，具体请遵医嘱</text>
        <CButton block @click="closeRescue">知道了</CButton>
        <CButton v-if="canSend" class="rescue__more" type="ghost" block @click="askCoachFromRescue">
          还要问教练 ›
        </CButton>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { onLoad, onShow } from '@dcloudio/uni-app'
import { chat, getTimes } from '@/api/ai'
import { useUserStore } from '@/stores/user'
import { useToast } from '@/composables/useToast'
import { track } from '@/utils/track'
import { redirectToLogin } from '@/utils/nav'

/** 单条消息：role=user 用户 / ai 教练；error=true 时以警示色展示 */
interface ChatMessage {
  role: 'user' | 'ai'
  text: string
  references?: string[]
  error?: boolean
  /** AI 回答满意度评分：undefined=未评；1~5=已评（每条仅评一次） */
  score?: number
}

/** 空会话引导问题 */
const QUICK_QUESTIONS = [
  '下午饿了能吃什么？',
  '这菜油多吗？',
  '今天为什么没瘦？',
  '晚餐怎么吃不超标？',
]

/**
 * 饥饿急救预置话术（06 §1.1 AI 主动介入：深夜防崩塌 / 下午茶防诱惑）。
 * 【假设】AI 知识库接口尚未提供急救专用端点，首期用预置话术兜底（不发请求、不扣次数）。
 */
const RESCUE_TIPS = [
  '先喝 300ml 温水，等 15 分钟再判断是不是真饿——很多时候只是渴。',
  '真饿了优先选高蛋白低热量：水煮蛋 1 个、无糖酸奶 1 杯、黄瓜/小番茄随意吃。',
  '避开"液体热量"：奶茶、果汁、含糖咖啡热量高还不顶饱。',
  '如果是深夜饥饿：先刷牙，刷完还饿就吃 1 个鸡蛋或 1 根香蕉，别开零食袋。',
  '吃完后记录一下，明天看看热量缺口有没有被抹平。',
]

/** 次数用尽的后端文案关键词（code 4001；request.ts 只抛 message，故按文案识别） */
const QUOTA_KEYWORDS = ['次数', '4001', 'quota']
/** 网络层失败关键词（request.ts fail / HTTP 非 2xx 文案） */
const NETWORK_KEYWORDS = ['网络', '请求失败', 'request:fail', '超时']
/** AI 不可用降级提示（06 §1.4：AI 服务超时） */
const AI_BUSY_TEXT = 'AI 正在思考，稍后再问'

const userStore = useUserStore()
const toast = useToast()

/** 会话 id：首次进入生成 uuid，仅存内存（重载页面新建会话） */
const sessionId = ref(genUuid())
const messages = ref<ChatMessage[]>([])
const draft = ref('')
const sending = ref(false)

/** 今日剩余次数：null=未拉取（加载中/失败兜底） */
const timesLeft = ref<number | null>(null)
const timesLoaded = ref(false)

const rescueVisible = ref(false)

/** scroll-view 锚点：滚到最后一条 */
const anchorId = ref('')

/** 未拉到次数时按"有次数"放行，避免网络抖动直接锁死输入框 */
const canSend = computed(() => {
  if (sending.value) return false
  if (!timesLoaded.value) return !!draft.value.trim()
  return timesLeft.value !== 0 && !!draft.value.trim()
})

const quotaText = computed(() => {
  if (!timesLoaded.value) return '次数加载中…'
  if (timesLeft.value === 0) return '今日剩余 0 次，邀请好友解锁'
  return `今日剩余 ${timesLeft.value} 次`
})

/** 生成 uuid（session_id 用；小程序无 crypto.randomUUID，手写 v4） */
function genUuid(): string {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = Math.floor(Math.random() * 16)
    const v = c === 'x' ? r : (r & 0x3) | 0x8
    return v.toString(16)
  })
}

/** 拉取今日剩余次数（失败保留 null，禁止发送逻辑按 timesLoaded 判断） */
async function loadTimes() {
  try {
    const data = await getTimes()
    timesLeft.value = data?.times_left ?? 0
  } catch (e) {
    // 错误信息已由 request.ts toast；此处只保证不锁死输入框
    void e
  } finally {
    timesLoaded.value = true
  }
}

function scrollToBottom() {
  nextTick(() => {
    anchorId.value = messages.value.length ? `msg-${messages.value.length - 1}` : ''
  })
}

function pushMessage(m: ChatMessage) {
  messages.value = [...messages.value, m]
  scrollToBottom()
}

/** 点击快捷问题：填入输入框并发送 */
function onPick(q: string) {
  draft.value = q
  onSend()
}

/** 发送（次数为 0 时 canSend=false，按钮与回车均被拦住） */
async function onSend() {
  if (!canSend.value || sending.value) return
  const text = draft.value.trim()
  if (!text) return

  draft.value = ''
  pushMessage({ role: 'user', text })
  sending.value = true
  try {
    const data = await chat({ session_id: sessionId.value, message: text })
    pushMessage({
      role: 'ai',
      text: data?.reply || '（AI 暂未给出回答，换个问法试试）',
      references: data?.references || [],
    })
    // 成功后以服务端返回为准同步剩余次数
    if (data && typeof data.times_left === 'number') timesLeft.value = data.times_left
    // AI 满意度（分母/关联）：完成一次问答
    track('ai_chat', { session_id: sessionId.value, intent: data?.intent || '' })
  } catch (e) {
    handleChatError(e)
  } finally {
    sending.value = false
  }
}

/**
 * AI 回答满意度评分（§1.6「AI 问答满意度 > 4.5/5」）。
 * 每条回答仅评一次，重复点击不重复计分；上报 ai_rating（score 1~5 + session_id）。
 */
function onRate(index: number, score: number) {
  const m = messages.value[index]
  if (!m || m.role !== 'ai' || m.error || m.score) return
  messages.value = messages.value.map((item, idx) => (idx === index ? { ...item, score } : item))
  track('ai_rating', { score, session_id: sessionId.value })
  toast.success({ title: '感谢你的评价' })
}

/**
 * 对话失败处理：
 * - 4001 次数用尽 → 次数置 0 并展示「邀请好友解锁」（文案由后端 message 给出）
 * - 网络层失败 → 保留 request.ts 原始提示
 * - 其余（6001 AI 不可用 / 超时）→ 降级提示「AI 正在思考，稍后再问」（06 §1.4）
 * - 1001/HTTP 401 已由 request.ts 静默刷新失败后 reLaunch 登录页，此处不再处理
 */
function handleChatError(e: unknown) {
  const msg = (e as Error)?.message || ''
  if (QUOTA_KEYWORDS.some((k) => msg.includes(k))) {
    timesLeft.value = 0
    timesLoaded.value = true
    pushMessage({ role: 'ai', text: msg || '今日对话次数已用完，邀请好友可解锁更多', error: true })
    loadTimes()
    return
  }
  const text = NETWORK_KEYWORDS.some((k) => msg.includes(k)) ? msg || '网络开小差了，请稍后重试' : AI_BUSY_TEXT
  pushMessage({ role: 'ai', text, error: true })
  if (text === AI_BUSY_TEXT) {
    // 覆盖 request.ts 已弹出的后端原始文案，保证用户看到的是约定降级话术
    uni.hideToast()
    toast.info({ title: AI_BUSY_TEXT })
  }
}

/* ---------- 饥饿急救弹窗 ---------- */

function openRescue() {
  rescueVisible.value = true
}
function closeRescue() {
  rescueVisible.value = false
}
/** 从弹窗转向真实提问（走正常 chat 流程，会计次数） */
function askCoachFromRescue() {
  closeRescue()
  draft.value = '我现在很饿，能吃什么？'
}

/** 次数用尽后的邀请入口（邀请裂变为 Phase 3，暂无落地页） */
function onInvite() {
  toast.info({ title: '邀请好友解锁（Phase 3 接入）' })
}

/* ---------- 生命周期 ---------- */

onLoad((options) => {
  // 首页「饥饿急救」跳入时带 hunger=1，直接弹预置话术
  if (options && options.hunger === '1') rescueVisible.value = true
})

onShow(() => {
  if (!userStore.isLogined) {
    redirectToLogin()
    return
  }
  loadTimes()
})
</script>

<style lang="scss" scoped>
.chat {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: $bg;

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

  &__refs {
    display: flex;
    flex-wrap: wrap;
    gap: $space-xs;
    margin-top: $space-xs;
  }

  &__ref {
    padding: 2rpx $space-xs;
    font-size: $t-22;
    color: $text-3;
    background: $bg;
    border-radius: $radius-sm;
  }

  &__disclaimer {
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
      color: #ffffff;
    }
  }
}

/* AI 满意度评分行（§1.6） */
.rate {
  display: flex;
  align-items: center;
  gap: $space-xs;
  margin-top: $space-xs;
  padding-top: $space-xs;
  border-top: 1rpx solid $border;

  &__label {
    font-size: $t-22;
    color: $text-3;
  }

  &__stars {
    display: flex;
    gap: 4rpx;
  }

  &__star {
    width: 36rpx;
    height: 36rpx;
  }
}

.chips {
  white-space: nowrap;
  padding-bottom: $space-sm;

  &__inner {
    display: inline-flex;
    gap: $space-sm;
  }

  &__item {
    flex-shrink: 0;
    padding: $space-xs $space-sm;
    font-size: $t-22;
    color: $text-2;
    background: $bg;
    border-radius: 999rpx;

    &--sos {
      color: $danger;
      background: rgba(239, 68, 68, 0.1);
    }
  }

  &--single {
    display: flex;
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

  // 次数用尽（06 §1.5 验收项）
  &--zero .quota__text {
    color: $danger;
  }
}

.mask {
  @include flex-center;

  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  left: 0;
  z-index: $z-mask;
  background: rgba(0, 0, 0, 0.5);
}

.rescue {
  z-index: $z-dialog;
  width: 600rpx;
  padding: $space-lg;
  background: $card;
  border-radius: $radius-lg;
  box-shadow: $shadow-lg;

  &__title {
    display: block;
    margin-bottom: $space-md;
    font-size: $t-28;
    font-weight: 500;
    color: $text-1;
  }

  &__item {
    display: flex;
    margin-bottom: $space-sm;
  }

  &__num {
    @include flex-center;

    flex-shrink: 0;
    width: 36rpx;
    height: 36rpx;
    margin-right: $space-sm;
    margin-top: 4rpx;
    font-size: $t-22;
    color: #ffffff;
    background: $brand;
    border-radius: 50%;
  }

  &__text {
    flex: 1;
    font-size: $t-26;
    line-height: 1.6;
    color: $text-1;
  }

  &__disclaimer {
    display: block;
    margin: $space-sm 0 $space-md;
    font-size: $t-22;
    color: $text-3;
  }

  &__more {
    margin-top: $space-sm;
  }
}
</style>
