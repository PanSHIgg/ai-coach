<template>
  <view class="page-shell">
    <!-- 未登录：无权限态（§5.8） -->
    <CNoPermission v-if="!userStore.isLogined" @action="goLogin" />

    <template v-else>
      <!-- 用户信息 + 权益标签（§5.5） -->
      <CCard class="me__user">
        <view class="me__row">
          <image
            v-if="userStore.detail?.avatar_url"
            class="me__avatar"
            :src="userStore.detail?.avatar_url"
            @error="onAvatarError"
          />
          <image v-else class="me__avatar" src="/static/avatar-default.png" />
          <view class="me__info">
            <text class="me__nickname">{{ userStore.nickname }}</text>
            <text class="me__tier">当前版本：{{ tierLabel }}</text>
          </view>
        </view>
      </CCard>

      <!-- 常用功能 -->
      <CCard title="常用" class="me__card">
        <view class="me__item" @tap="goEdit">
          <text class="me__item-label">身体档案</text>
          <text class="me__item-arrow">›</text>
        </view>
        <view class="me__item" @tap="goAccountDetail">
          <text class="me__item-label">热量账户详情</text>
          <text class="me__item-arrow">›</text>
        </view>
        <view class="me__item" @tap="goWeight">
          <text class="me__item-label">体重记录</text>
          <text class="me__item-arrow">›</text>
        </view>
        <!-- 「记录」已从 Tab 降为普通页（§3.2），由我的页保留入口 -->
        <view class="me__item" @tap="goRecord">
          <text class="me__item-label">记录</text>
          <text class="me__item-arrow">›</text>
        </view>
        <!-- 邀请解锁入口（docs/split/03:527 我的·立即邀请 → 邀请页） -->
        <view class="me__item" @tap="goInvite">
          <text class="me__item-label">立即邀请</text>
          <text class="me__item-arrow">›</text>
        </view>
      </CCard>

      <!-- 提醒订阅（§2.3.1 餐前/深夜推送；§2.4 未授权引导设置页，不阻断核心流程） -->
      <CCard title="提醒" class="me__card">
        <view class="me__item" @tap="onSubscribe">
          <text class="me__item-label">提醒订阅</text>
          <text class="me__item-status" :class="{ 'me__item-status--on': subscribedTypes.size > 0 }">
            {{ subscribeStatusText }}
          </text>
        </view>
      </CCard>

      <!-- 账号 -->
      <CCard title="账号" class="me__card">
        <view class="me__item" @tap="onLogout">
          <text class="me__item-label me__item-label--danger">退出登录</text>
          <text class="me__item-arrow">›</text>
        </view>
      </CCard>
    </template>
  </view>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { useUserStore } from '@/stores/user'
import { redirectToLogin } from '@/utils/nav'
import { getSubscriptions } from '@/api/notification'
import { useSubscribe } from '@/composables/useSubscribe'

const userStore = useUserStore()
const { requestSubscribe } = useSubscribe()

// 权益档位文案（§5.5：0基础 1进阶 2高级 3终身）
const TIER_LABEL: Record<number, string> = {
  0: '基础版（免费）',
  1: '进阶版',
  2: '高级版',
  3: '终身版',
}
const tierLabel = computed(() => TIER_LABEL[userStore.tier] || '基础版（免费）')

// 已订阅提醒的模板类型（status=1）
const subscribedTypes = ref<Set<number>>(new Set())
const subscribeStatusText = computed(() => (subscribedTypes.value.size > 0 ? '已开启' : '未开启'))

onShow(() => {
  if (userStore.isLogined) {
    userStore.fetchMe()
    loadSubscriptions()
  }
})

/** 静默拉取订阅状态（失败不阻断、不弹 toast） */
async function loadSubscriptions() {
  try {
    const data = await getSubscriptions(true)
    subscribedTypes.value = new Set(
      data.items.filter((i) => i.status === 1).map((i) => i.template_type),
    )
  } catch {
    // 忽略：状态展示非核心，失败不影响入口可用
  }
}

/** 点击入口：申请订阅授权（未授权则引导设置页）+ 刷新状态；均不阻断核心流程 */
async function onSubscribe() {
  await requestSubscribe()
  loadSubscriptions()
}

function goLogin() {
  redirectToLogin()
}
/** 外链头像加载失败 → 回退本地默认头像（置空触发 v-else 分支） */
function onAvatarError() {
  if (userStore.detail) userStore.detail.avatar_url = ''
}
function goEdit() {
  uni.navigateTo({ url: '/pages/profile/edit' })
}
function goAccountDetail() {
  uni.navigateTo({ url: '/pages/account' })
}
function goWeight() {
  uni.navigateTo({ url: '/pages/weight/weight' })
}
function goRecord() {
  uni.navigateTo({ url: '/pages/record/record' })
}
function goInvite() {
  uni.navigateTo({ url: '/pages/invite' })
}
function onLogout() {
  uni.showModal({
    title: '退出登录',
    content: '确定要退出当前账号吗？',
    confirmText: '退出',
    confirmColor: '#ef4444',
    success: (res) => {
      if (res.confirm) userStore.logout()
    },
  })
}
</script>

<style lang="scss" scoped>
.page-shell {
  padding: $space-md;
}

.me {
  &__user {
    margin-bottom: $space-md;
  }

  &__row {
    display: flex;
    align-items: center;
  }

  &__avatar {
    width: 96rpx;
    height: 96rpx;
    margin-right: $space-md;
    background: $bg;
    border-radius: 50%;
  }

  &__info {
    display: flex;
    flex-direction: column;
  }

  &__nickname {
    font-size: $t-28;
    font-weight: 500;
    color: $text-1;
  }

  &__tier {
    margin-top: 4rpx;
    font-size: $t-22;
    color: $text-3;
  }

  &__card {
    margin-bottom: $space-md;
  }

  &__item {
    @include flex-between;

    padding: $space-sm 0;

    &:not(:last-child) {
      @include hairline(bottom);
    }
  }

  &__item-label {
    font-size: $t-26;
    color: $text-1;

    &--danger {
      color: $danger;
    }
  }

  &__item-arrow {
    font-size: $t-24;
    color: $text-3;
  }

  &__item-status {
    font-size: $t-24;
    color: $text-3;

    &--on {
      color: $brand;
    }
  }
}
</style>