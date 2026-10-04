<template>
  <view class="ctopbar">
    <!-- 占位：撑开固定顶栏的高度，页面内容从顶栏下方开始 -->
    <view class="ctopbar__spacer" :style="{ height: totalHeight + 'px' }" />
    <view class="ctopbar__fixed">
      <view class="ctopbar__status" :style="{ height: statusHeight + 'px' }" />
      <view
        class="ctopbar__row"
        :style="{ height: navHeight + 'px', paddingRight: rightPad + 'px' }"
      >
        <view v-if="leftText" class="ctopbar__left" @tap="emit('left')">
          <text class="ctopbar__left-text">{{ leftText }}</text>
          <text class="ctopbar__caret">▼</text>
        </view>
        <text v-if="title" class="ctopbar__title">{{ title }}</text>
        <view v-if="bell" class="ctopbar__bell" @tap="emit('bell')">
          <image class="ctopbar__bell-icon" src="/static/icons/ic-bell.png" mode="aspectFit" />
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
/**
 * 顶部导航栏（§4.10：底白、边 --border、标题居中、右侧可选操作；§5.x 原型顶栏 🔔）。
 * Tab 页配 navigationStyle=custom 使用：状态栏占位 + 与微信胶囊按钮垂直对齐的导航行，
 * 右侧操作止于胶囊左缘，避免与胶囊重叠。H5 / 取不到胶囊时回退 44px 行高。
 */
withDefaults(
  defineProps<{
    /** 居中标题（与 leftText 二选一） */
    title?: string
    /** 左侧入口文案（首页「我的体重档案 ▼」，§5.1-1） */
    leftText?: string
    /** 右侧 🔔（消息中心二期接入，先占位） */
    bell?: boolean
  }>(),
  { title: '', leftText: '', bell: true },
)

const emit = defineEmits<{ left: []; bell: [] }>()

const info = uni.getWindowInfo()
const statusHeight = info.statusBarHeight || 0
let navHeight = 44
let rightPad = 12
const rect =
  typeof uni.getMenuButtonBoundingClientRect === 'function'
    ? uni.getMenuButtonBoundingClientRect()
    : null
if (rect && rect.height > 0) {
  navHeight = rect.height + (rect.top - statusHeight) * 2
  rightPad = Math.max(rightPad, info.windowWidth - rect.left + 8)
}
const totalHeight = statusHeight + navHeight
</script>

<style lang="scss" scoped>
.ctopbar {
  &__fixed {
    @include hairline(bottom);

    position: fixed;
    top: 0;
    right: 0;
    left: 0;
    z-index: $z-nav;
    background: $card;
  }

  &__row {
    position: relative;
    display: flex;
    align-items: center;
    padding-left: $space-md;
  }

  &__left {
    @include flex-center;
    @include press;

    min-width: 0;
  }

  &__left-text {
    @include ellipsis;

    font-size: $t-32;
    font-weight: 500;
    color: $text-1;
  }

  &__caret {
    margin-left: 4rpx;
    font-size: $t-22;
    color: $text-3;
  }

  &__title {
    @include ellipsis;

    position: absolute;
    right: 0;
    left: 0;
    padding: 0 96rpx;
    font-size: $t-32;
    font-weight: 500;
    color: $text-1;
    text-align: center;
    pointer-events: none;
  }

  &__bell {
    @include flex-center;
    @include press;

    position: relative;
    margin-left: auto;
    width: 64rpx;
    height: 64rpx;
  }

  &__bell-icon {
    width: 40rpx;
    height: 40rpx;
  }
}
</style>
