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
    <view v-if="progress?.poster_url && !posterFailed" class="invite__poster">
      <image
        class="invite__poster-img"
        :src="progress.poster_url"
        mode="widthFix"
        @error="posterFailed = true"
      />
    </view>

    <!-- 3. 立即邀请（open-type=share 拉起微信会话分享；分享路径带 inviter_id；达终身版后换文案 §2.4） -->
    <button
      class="invite__share-btn"
      open-type="share"
      :disabled="loading"
      @tap="trackShare"
    >
      {{ reachedMax ? '继续邀请帮助更多人' : '立即邀请好友' }}
    </button>

    <!-- 4. 活动规则（邀请规则新口径：注册即有效，2026-10-01 变更） -->
    <CCard title="活动规则" class="invite__card">
      <text class="invite__rule">1. 被邀请人注册成功即算有效邀请，权益实时到账。</text>
      <text class="invite__rule">2. 只算直接邀请：好友再邀请他人与你无关。</text>
      <text class="invite__rule">3. 累计 1 / 3 / 10 人分别解锁 20 次/日、40 次/日、不限次（终身版）。</text>
      <text class="invite__rule">4. 同一设备只计 1 次，防刷违规将被拒绝。权益长期有效，不设期限。</text>
    </CCard>
  </view>
</template>

<script setup lang="ts">
/**
 * FE · 邀请裂变页 — CD-05
 * 依据：docs/split/01 §3.1 #21 /pages/invite（进度、海报、规则、分享）、§2.3.3 邀请裂变流程、
 *      docs/split/03:527 我的·立即邀请入口（invite_share / invite_accept）。
 * 契约：GET /api/invite/progress、POST /api/invite（不动 invite schema）。
 * 【假设】① 分享落地即本页：onLoad 解析 inviter_id（最小侵入挂载点），未登录时先落 storage，
 *           登录后再次进入本页（或从"我的"入口进入）自动补绑；
 *         ② invite_accept 在绑定接口成功时上报（新口径：注册即有效，绑定成功即计入，前端无额外信号）；
 *         ③ channel 固定 wechat_session（首期仅会话分享）。
 */
import { computed, ref } from 'vue'
import { onLoad, onShareAppMessage } from '@dcloudio/uni-app'
import { bindInvite, getInviteProgress } from '@/api/invite'
import { useUserStore } from '@/stores/user'
import { track, getDeviceId } from '@/utils/track'
import { useToast } from '@/composables/useToast'
import type { InviteProgressData } from '@/types/api'

/** 防刷违规错误码（同一设备仅可参与一次，2026-10-01 邀请规则变更） */
const CODE_INVITE_DEVICE_LIMIT = 4102

/** 档位里程碑（仅展示卡：1/3/10 人 → 20 次/日 / 40 次/日 / 不限次；下一档以接口 next_tier 为准） */
const TIERS = [
  { need: 1, label: '20 次/日' },
  { need: 3, label: '40 次/日' },
  { need: 10, label: '不限次（终身版）' },
] as const

/** 未登录时暂存 inviter_id，登录后补绑 */
const PENDING_INVITER_KEY = 'pending_inviter_id'

const userStore = useUserStore()
const progress = ref<InviteProgressData | null>(null)
const loading = ref(true)
/** 海报外链加载失败 → 整块隐藏（不展示破图） */
const posterFailed = ref(false)

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

/** 已达终身版（tier3/不限次）：分享按钮换「继续邀请帮助更多人」 */
const reachedMax = computed(() => (progress.value?.benefit?.tier ?? 0) >= 3)

/* ---------- 数据 ---------- */

async function loadProgress() {
  loading.value = true
  try {
    progress.value = await getInviteProgress()
    posterFailed.value = false
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
    await bindInvite(inviterId, getDeviceId())
    track('invite_accept', { inviter_id: inviterId })
    await loadProgress()
  } catch (e) {
    // 已绑定 / 无效码：静默，进度以服务端为准；4102 防刷违规需明示用户
    if ((e as { code?: number }).code === CODE_INVITE_DEVICE_LIMIT) {
      useToast().error({ title: '邀请受限：同一设备仅可参与一次' })
    }
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
    path: `/pages/invite${inviterId ? `?inviter_id=${inviterId}` : ''}`,
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
    color: var(--card);
    background: $brand;
    border-radius: $radius;

    // 重置微信原生按钮默认样式
    &::after {
      border: none;
    }

    &[disabled] {
      color: var(--card);
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
