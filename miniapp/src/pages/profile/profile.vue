<template>
  <view class="page-shell">
    <!-- 用户卡 -->
    <CCard class="me__user">
      <view class="me__row">
        <view class="me__avatar">🧑</view>
        <view>
          <text class="me__nickname">{{ userStore.nickname }}</text>
          <text class="me__sub">{{ userStore.isLogined ? '已登录' : '未登录' }}</text>
        </view>
      </view>
    </CCard>

    <!-- 菜单 -->
    <CCard title="常用" class="me__card">
      <view class="me__item" @tap="goEdit">
        <text class="me__item-label">身体档案</text>
        <text class="me__item-arrow">→</text>
      </view>
      <view class="me__item" @tap="goAccountDetail">
        <text class="me__item-label">热量账户详情</text>
        <text class="me__item-arrow">→</text>
      </view>
      <view class="me__item" @tap="onLogout">
        <text class="me__item-label me__item-label--danger">退出登录</text>
        <text class="me__item-arrow">→</text>
      </view>
    </CCard>
  </view>
</template>

<script setup lang="ts">
import { useUserStore } from '@/stores/user'

const userStore = useUserStore()

function goEdit() {
  uni.navigateTo({ url: '/pages/profile/edit' })
}

function goAccountDetail() {
  uni.navigateTo({ url: '/pages/account/detail' })
}

function onLogout() {
  userStore.logout()
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
    @include flex-center;

    width: 96rpx;
    height: 96rpx;
    margin-right: $space-md;
    font-size: 48rpx;
    background: $bg;
    border-radius: 50%;
  }

  &__nickname {
    display: block;
    font-size: $t-28;
    font-weight: 500;
    color: $text-1;
  }

  &__sub {
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
}
</style>
