<template>
  <view class="pv">
    <!-- 未登录（§5.8 无权限态） -->
    <CNoPermission v-if="!userStore.isLogined" text="登录后管理隐私" @action="goLogin" />

    <template v-else>
      <CCard title="隐私控制" class="pv__card">
        <CSkeleton v-if="loading" type="card" />
        <CError v-else-if="error" @retry="load" />
        <template v-else-if="privacy">
          <view v-for="it in SWITCHES" :key="it.key" class="pv__row">
            <view class="pv__meta">
              <text class="pv__label">{{ it.label }}</text>
              <text class="pv__desc">{{ it.desc }}</text>
            </view>
            <switch
              class="pv__switch"
              :checked="privacy[it.key]"
              color="#22c55e"
              :disabled="saving"
              @change="onSwitch(it.key, $event)"
            />
          </view>
        </template>
      </CCard>

      <!-- 一键删除（账号注销：DELETE /api/account） -->
      <CCard title="账号注销" class="pv__card">
        <text class="pv__danger-desc">
          注销后你的档案、记录、积分、券等数据将被级联清除且不可恢复，请谨慎操作。
        </text>
        <CButton type="danger" block :loading="deleting" @click="onDeleteAccount">一键删除</CButton>
      </CCard>
    </template>
  </view>
</template>

<script setup lang="ts">
/**
 * FE · 隐私控制 — G3
 * 依据：docs/split/03 §5.5-8 隐私控制（匿名身份 / 脱敏分享开关 / 可见性设置 / 一键删除）
 * 契约：GET /api/privacy、PUT /api/privacy（部分字段）、DELETE /api/account（账号注销）
 * 【假设】① 开关切换采用乐观更新，PUT 失败回滚并提示；
 *         ② 「一键删除」后端由账户域实现（DELETE /api/account），本波若未就绪，
 *            调用失败时给出降级提示且不改动本地登录态；
 *         ③ 采用原生 switch 组件（与 pages/community/post.vue 匿名开关一致）。
 */
import { ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { useUserStore } from '@/stores/user'
import { useToast } from '@/composables/useToast'
import { redirectToLogin } from '@/utils/nav'
import { getPrivacy, updatePrivacy, deleteAccount } from '@/api/privacy'
import type { PrivacyData } from '@/types/api'

const userStore = useUserStore()
const toast = useToast()

/** 开关项（顺序与展示文案） */
const SWITCHES: { key: keyof PrivacyData; label: string; desc: string }[] = [
  { key: 'anonymous', label: '匿名身份', desc: '在社区与榜单以匿名身份展示' },
  { key: 'mask_share', label: '脱敏分享', desc: '分享报告时隐藏体重等敏感数值' },
  { key: 'visibility_leaderboard', label: '排行榜可见', desc: '允许在排行榜展示我的昵称' },
  { key: 'visibility_community', label: '社区可见', desc: '允许其他用户查看我的动态' },
  { key: 'allow_data_export', label: '数据导出授权', desc: '允许导出含体重的健康报告' },
]

const privacy = ref<PrivacyData | null>(null)
const loading = ref(false)
const error = ref(false)
const saving = ref(false)
const deleting = ref(false)

onShow(() => {
  if (userStore.isLogined) load()
})

async function load() {
  loading.value = true
  error.value = false
  try {
    privacy.value = await getPrivacy()
  } catch (e) {
    privacy.value = null
    error.value = true
    void e
  } finally {
    loading.value = false
  }
}

/** 开关切换：乐观更新 → PUT 部分字段 → 失败回滚 */
async function onSwitch(field: keyof PrivacyData, e: Event) {
  if (!privacy.value || saving.value) return
  const value = !!(e as unknown as { detail?: { value?: boolean } })?.detail?.value
  const prev = privacy.value[field]
  if (value === prev) return
  privacy.value[field] = value
  saving.value = true
  try {
    privacy.value = await updatePrivacy({ [field]: value })
  } catch (err) {
    // 回滚到切换前状态（错误信息已由 request 统一 toast）
    if (privacy.value) privacy.value[field] = prev
    void err
  } finally {
    saving.value = false
  }
}

/** 一键删除：二次确认后注销账号 */
function onDeleteAccount() {
  uni.showModal({
    title: '注销账号',
    content: '注销后全部数据将被级联清除且不可恢复，确定继续吗？',
    confirmText: '确认注销',
    confirmColor: '#ef4444',
    success: (res) => {
      if (res.confirm) void doDelete()
    },
  })
}

async function doDelete() {
  if (deleting.value) return
  deleting.value = true
  try {
    await deleteAccount()
    toast.success({ title: '账号已注销' })
    userStore.logout()
  } catch (e) {
    // 后端未就绪/失败：降级提示，保留登录态
    void e
    toast.error({ title: '注销失败，请稍后重试或联系客服' })
  } finally {
    deleting.value = false
  }
}

function goLogin() {
  redirectToLogin()
}
</script>

<style lang="scss" scoped>
.pv {
  padding: $space-md;

  &__card {
    margin-bottom: $space-md;
  }

  &__row {
    @include flex-between;

    padding: $space-sm 0;

    &:not(:last-child) {
      @include hairline(bottom);
    }
  }

  &__meta {
    flex: 1;
    min-width: 0;
    margin-right: $space-sm;
  }

  &__label {
    display: block;
    font-size: $t-26;
    color: $text-1;
  }

  &__desc {
    display: block;
    margin-top: 4rpx;
    font-size: $t-22;
    color: $text-3;
  }

  &__switch {
    flex: none;
    transform: scale(0.85);
  }

  &__danger-desc {
    display: block;
    margin-bottom: $space-md;
    font-size: $t-22;
    color: $text-2;
  }
}
</style>