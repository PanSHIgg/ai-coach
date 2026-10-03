<template>
  <view class="task">
    <!-- 未登录（§5.8 无权限态） -->
    <CNoPermission v-if="!userStore.isLogined" text="登录后查看任务" @action="goLogin" />

    <template v-else>
      <!-- 签到概览 -->
      <CCard class="task__card">
        <view class="task__head">
          <view>
            <text class="task__head-title">每日签到</text>
            <text class="task__head-sub">连续签到 {{ streak }} 天</text>
          </view>
          <CButton
            size="md"
            :loading="checking"
            :disabled="checkedToday"
            @click="onCheckin"
          >
            {{ checkedToday ? '今日已签到' : '立即签到' }}
          </CButton>
        </view>
      </CCard>

      <CCard title="任务中心" class="task__card">
        <CSkeleton v-if="loading" type="card" />
        <CError v-else-if="error" @retry="load" />
        <CEmpty
          v-else-if="!tasks.length"
          icon="empty-coupon"
          text="暂无可做任务"
          button-text=""
        />
        <view v-else>
          <view v-for="t in tasks" :key="t.code" class="task-item">
            <view class="task-item__main">
              <text class="task-item__name">{{ t.name }}</text>
              <text class="task-item__reward">{{ rewardText(t) }}</text>
              <view v-if="showProgress(t)" class="task-item__bar">
                <view class="task-item__bar-inner" :style="{ width: `${clampPct(t.progress)}%` }" />
              </view>
            </view>
            <view class="task-item__action">
              <text v-if="t.status === 1" class="task-item__done">已完成</text>
              <CButton v-else size="sm" @click="onTask(t)">去完成</CButton>
            </view>
          </view>
        </view>
      </CCard>
    </template>
  </view>
</template>

<script setup lang="ts">
/**
 * FE · 任务中心 / 每日签到 — G3
 * 依据：docs/split/03 §5.5-5 任务中心（每日签到+5积分 / 完善档案送轻食券 / 首次AI检测送运动券）
 * 契约：GET /api/task/list（status 1 已完成；progress 百分比或步数）、POST /api/task/checkin（当日幂等）
 * 【假设】① 连续天数仅由签到响应 streak 下发，未签到前本地从 0 起显示；
 *         ② 「完善档案 / 首次AI检测」未完成时点击分别跳档案页 / 吃什么页引导完成。
 */
import { computed, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { useUserStore } from '@/stores/user'
import { useToast } from '@/composables/useToast'
import { redirectToLogin } from '@/utils/nav'
import { getTaskList, checkin } from '@/api/task'
import type { TaskItem } from '@/types/api'

const userStore = useUserStore()
const toast = useToast()

const tasks = ref<TaskItem[]>([])
const loading = ref(false)
const error = ref(false)
const checking = ref(false)
const streak = ref(0)

/** 每日签到任务（用于判断今日是否已签到） */
const checkinTask = computed(() => tasks.value.find((t) => t.code === 'daily_checkin'))
const checkedToday = computed(() => checkinTask.value?.status === 1)

/** 未完成任务的引导路由 */
const TASK_ROUTE: Record<string, string> = {
  complete_profile: '/pages/profile/edit',
  first_ai_check: '/pages/eat',
}

function rewardText(t: TaskItem): string {
  const desc = t.reward_desc?.trim()
  if (desc) return desc
  return t.reward_points > 0 ? `+${t.reward_points} 积分` : ''
}

function showProgress(t: TaskItem): boolean {
  return t.status !== 1 && t.progress > 0 && t.progress < 100
}

function clampPct(n: number): number {
  return Math.min(100, Math.max(0, n))
}

onShow(() => {
  if (userStore.isLogined) load()
})

async function load() {
  loading.value = true
  error.value = false
  try {
    const data = await getTaskList()
    tasks.value = data?.items ?? []
  } catch (e) {
    tasks.value = []
    error.value = true
    void e
  } finally {
    loading.value = false
  }
}

/** 每日签到：成功刷新列表并提示得分 / 连续天数 */
async function onCheckin() {
  if (checking.value || checkedToday.value) return
  checking.value = true
  try {
    const res = await checkin()
    streak.value = res.streak
    if (res.points_added > 0) {
      toast.success({ title: `签到成功 +${res.points_added} 积分` })
    } else {
      toast.info({ title: `今日已签到，连续 ${res.streak} 天` })
    }
    await load()
  } catch (e) {
    // 错误信息已由 request 封装 toast
  } finally {
    checking.value = false
  }
}

/** 非签到任务：按 code 跳引导页 */
function onTask(t: TaskItem) {
  const url = TASK_ROUTE[t.code]
  if (url) {
    uni.navigateTo({ url })
    return
  }
  toast.info({ title: '该任务暂无可操作入口' })
}

function goLogin() {
  redirectToLogin()
}
</script>

<style lang="scss" scoped>
.task {
  padding: $space-md;

  &__card {
    margin-bottom: $space-md;
  }

  &__head {
    @include flex-between;
  }

  &__head-title {
    display: block;
    font-size: $t-32;
    font-weight: 500;
    color: $text-1;
  }

  &__head-sub {
    display: block;
    margin-top: 4rpx;
    font-size: $t-22;
    color: $text-3;
  }
}

.task-item {
  @include flex-between;

  padding: $space-sm 0;

  &:not(:last-child) {
    @include hairline(bottom);
  }

  &__main {
    flex: 1;
    min-width: 0;
    margin-right: $space-sm;
  }

  &__name {
    display: block;
    font-size: $t-26;
    color: $text-1;
  }

  &__reward {
    display: block;
    margin-top: 4rpx;
    font-size: $t-22;
    color: $text-3;
  }

  &__bar {
    height: 12rpx;
    margin-top: $space-xs;
    overflow: hidden;
    background: $bg;
    border-radius: 999rpx;
  }

  &__bar-inner {
    height: 100%;
    background: $brand;
    border-radius: 999rpx;
  }

  &__action {
    flex: none;
  }

  &__done {
    font-size: $t-24;
    color: $brand;
  }
}
</style>