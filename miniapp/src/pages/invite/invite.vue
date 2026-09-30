<template>
  <view class="page-shell invite">
    <!-- 1. 邀请进度卡：有效邀请数 / 档位里程碑 / 下一档 -->
    <CCard class="invite__card">
      <view class="invite__count">
        <text class="invite__num">{{ progress?.invitee_count ?? 0 }}</text>
        <text class="invite__num-label">有效邀请（人）</text>
      </view>

      <view class="invite__tiers">
        <view
          v-for="t in TIERS"
          :key="t.need"
          class="invite__tier"
          :class="{ 'invite__tier--reached': reached(t.need) }"
        >
          <text class="invite__tier-need">{{ t.need }} 人</text>
          <text class="invite__tier-reward">{{ t.label }}</text>
        </view>
      </view>

      <text v-if="progress?.next_tier" class="invite__next">
        再邀请 {{ progress.next_tier.need }} 人，解锁{{ progress.next_tier.reward }}
      </text>
      <text v-if="benefitText" class="invite__benefit">当前权益：{{ benefitText }}</text>
    </CCard>

    <!-- 2. 分享海报位（poster_url 有则显示） -->
    <view v-if="progress?.poster_url" class="invite__poster">
      <image class="invite__poster-img" :src="progress.poster_url" mode="widthFix" />
    </view>

    <!-- 3. 立即邀请（open-type=share 拉起微信会话分享；分享路径带 inviter_id） -->
    <button
      class="invite__share-btn"
      open-type="share"
      :disabled="loading"
      @tap="trackShare"
    >
      立即邀请好友
    </button>

    <!-- 4. 活动规则（01 §2.3.3） -->
    <CCard title="活动规则" class="invite__card">
      <text class="invite__rule">1. 累计邀请 2 / 5 / 10 位好友，分别解锁进阶版 90 天 / 180 天 / 永久（终身教练）。</text>
      <text class="invite__rule">2. 邀请成功后双方各得券。</text>
      <text class="invite__rule">3. 被邀请人完成 1 次拍照记录后邀请才生效。</text>
      <text class="invite__rule">4. 同设备只计 1 次，单人奖励上限 180 天。</text>
    </CCard>
  </view>
</template>

<script setup lang="ts">
/**
 * FE · 邀请裂变页 — CD-05
 * 依据：docs/split/01 §3.1 #21 /pages/invite（进度、海报、规则、分享）、§2.3.3 邀请裂变流程、
 *      docs/split/03:527 我的·立即邀请入口、docs/前端埋点接入说明.md（invite_share / invite_accept）。
 * 契约：GET /api/invite/progress、POST /api/invite（不动 invite schema）。
 * 【假设】① 分享落地即本页：onLoad 解析 inviter_id（最小侵入挂载点），未登录时先落 storage，
 *           登录后再次进入本页（或从"我的"入口进入）自动补绑；
 *         ② invite_accept 在绑定接口成功时上报（服务端"有效"口径需被邀请人完成拍照，前端无信号）；
 *         ③ channel 固定 wechat_session（首期仅会话分享）。
 */
import { computed, ref } from 'vue'
import { onLoad, onShareAppMessage } from '@dcloudio/uni-app'
import { bindInvite, getInviteProgress } from '@/api/invite'
import { useUserStore } from '@/stores/user'
import { track } from '@/utils/track'
import type { InviteProgressData } from '@/types/api'

/** 档位里程碑（01 §2.3.3：2/5/10 人 → 进阶版 90 天 / 180 天 / 永久） */
const TIERS = [
  { need: 2, label: '进阶版 90 天' },
  { need: 5, label: '进阶版 180 天' },
  { need: 10, label: '永久（终身教练）' },
] as const

/** 未登录时暂存 inviter_id，登录后补绑 */
const PENDING_INVITER_KEY = 'pending_inviter_id'

const userStore = useUserStore()
const progress = ref<InviteProgressData | null>(null)
const loading = ref(true)

/** 当前权益文案（tier：0基础 1进阶 2高级 3终身，对齐 §5.5） */
const benefitText = computed(() => {
  const b = progress.value?.benefit
  if (!b) return ''
  const label = { 0: '基础版', 1: '进阶版', 2: '高级版', 3: '终身版' }[b.tier] || '基础版'
  if (!b.valid_to) return b.tier >= 3 ? '终身有效' : label
  return `${label}（至 ${b.valid_to.slice(0, 10)}）`
})

function reached(need: number): boolean {
  return (progress.value?.invitee_count ?? 0) >= need
}

/* ---------- 数据 ---------- */

async function loadProgress() {
  loading.value = true
  try {
    progress.value = await getInviteProgress()
  } catch (e) {
    // request 层已统一 toast / 401 跳登录；本地保留空态
  } finally {
    loading.value = false
  }
}

/* ---------- 绑定（被邀请人侧） ---------- */

function trackShare() {
  track('invite_share', { channel: 'wechat_session' })
}

async function tryBind(inviterId: number) {
  // 不能邀请自己（后端同样校验，前端提前拦截）
  if (inviterId === userStore.detail?.id) return
  try {
    await bindInvite(inviterId)
    track('invite_accept', { inviter_id: inviterId })
    await loadProgress()
  } catch {
    /* 已绑定 / 无效码 / 上限：静默，进度以服务端为准 */
  }
}

function tryBindPending() {
  const pending = Number(uni.getStorageSync(PENDING_INVITER_KEY))
  if (!Number.isInteger(pending) || pending <= 0) return
  uni.removeStorageSync(PENDING_INVITER_KEY) // 取出即清，防重复绑
  void tryBind(pending)
}

/* ---------- 分享 ---------- */

onShareAppMessage(() => {
  const inviterId = userStore.detail?.id
  return {
    // 【假设】分享标题文案文档未定稿，按 01 §2.3.3 利益点提炼
    title: '一起用 AI 饮食管控教练，记录饮食领奖励！',
    path: `/pages/invite/invite${inviterId ? `?inviter_id=${inviterId}` : ''}`,
  }
})

/* ---------- 生命周期 ---------- */

onLoad((query) => {
  const inviterId = Number(query?.inviter_id)
  if (Number.isInteger(inviterId) && inviterId > 0) {
    // 先落 storage：未登录时参数不因跳登录页丢失，登录后进入本页自动补绑
    uni.setStorageSync(PENDING_INVITER_KEY, inviterId)
  }
  if (userStore.isLogined) {
    if (!userStore.detail) void userStore.fetchMe()
    tryBindPending()
  }
  void loadProgress()
})
</script>

<style lang="scss" scoped>
.page-shell {
  padding: $space-md;
  padding-bottom: calc(#{$space-xl} + env(safe-area-inset-bottom));
}

.invite {
  &__card {
    margin-bottom: $space-md;
  }

  // 1. 进度卡
  &__count {
    @include flex-center(column);

    padding: $space-sm 0 $space-md;
  }

  &__num {
    font-size: $t-num-lg;
    font-weight: 700;
    color: $brand;
  }

  &__num-label {
    margin-top: 4rpx;
    font-size: $t-22;
    color: $text-3;
  }

  &__tiers {
    display: flex;
    gap: $space-sm;
    margin-bottom: $space-md;
  }

  &__tier {
    @include flex-center(column);

    flex: 1;
    padding: $space-sm 0;
    background: $bg;
    border: 1rpx solid $border;
    border-radius: $radius-sm;

    &--reached {
      background: rgba(34, 197, 94, 0.1);
      border-color: $brand;
    }
  }

  &__tier-need {
    font-size: $t-24;
    font-weight: 500;
    color: $text-1;
  }

  &__tier-reward {
    margin-top: 4rpx;
    font-size: $t-22;
    color: $text-3;
  }

  &__next {
    display: block;
    font-size: $t-26;
    color: $text-1;
  }

  &__benefit {
    display: block;
    margin-top: $space-xs;
    font-size: $t-22;
    color: $text-3;
  }

  // 2. 海报位
  &__poster {
    margin-bottom: $space-md;
    overflow: hidden;
    background: $card;
    border-radius: $radius;
    box-shadow: $shadow;
  }

  &__poster-img {
    display: block;
    width: 100%;
  }

  // 3. 分享按钮（原生 button 承载 open-type=share，样式对齐 CButton primary lg block）
  &__share-btn {
    @include flex-center;
    @include press;

    width: 100%;
    height: 88rpx;
    margin-bottom: $space-md;
    font-size: $t-28;
    font-weight: 500;
    color: #ffffff;
    background: $brand;
    border-radius: $radius;

    // 重置微信原生按钮默认样式
    &::after {
      border: none;
    }

    &[disabled] {
      color: #ffffff;
      background: $disabled;
    }
  }

  // 4. 活动规则
  &__rule {
    display: block;
    margin-bottom: $space-xs;
    font-size: $t-24;
    line-height: 1.6;
    color: $text-2;

    &:last-child {
      margin-bottom: 0;
    }
  }
}
</style>
