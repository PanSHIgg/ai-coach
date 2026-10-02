<template>
  <view class="rp">
    <!-- 未登录（§5.8 无权限态） -->
    <CNoPermission v-if="!userStore.isLogined" text="登录后导出报告" @action="goLogin" />

    <template v-else>
      <!-- 报告导出 -->
      <CCard title="报告导出" class="rp__card">
        <view class="rp__btn-row">
          <CButton block :loading="exporting" @click="onExport">导出体重健康报告</CButton>
        </view>
        <view class="rp__btn-row">
          <CButton block type="secondary" @click="onShare">分享报告</CButton>
        </view>
        <text class="rp__tip">报告为 CSV 文本，含体重/BMI/体脂/腰围与饮食运动记录</text>
      </CCard>

      <!-- 热量周报入口 -->
      <CCard title="热量周报" class="rp__card">
        <view class="rp__item" @tap="goWeekly">
          <view class="rp__item-main">
            <text class="rp__item-label">查看本周热量控制周报</text>
            <text class="rp__item-desc">缺口 · 步数 · 体重趋势 · AI 点评</text>
          </view>
          <text class="rp__item-arrow">›</text>
        </view>
      </CCard>
    </template>
  </view>
</template>

<script setup lang="ts">
/**
 * FE · 报告导出 — G3
 * 依据：docs/split/03 §5.5-9 报告导出（[导出体重健康报告][分享报告]）
 * 契约：POST /api/report/export（report_type=weight, format=csv）
 * 【假设】① 导出内容为 CSV 文本：H5 端用 Blob + a[download] 触发下载；
 *            小程序端不支持文件下载，降级为 uni.setClipboardData 复制内容；
 *         ② 分享优先尝试 uni.share（App/部分平台），不可用或失败时降级复制分享文案；
 *         ③ 周报入口跳 pages/report/weekly。
 */
import { ref } from 'vue'
import { useUserStore } from '@/stores/user'
import { useToast } from '@/composables/useToast'
import { redirectToLogin } from '@/utils/nav'
import { exportReport } from '@/api/report'
import type { ReportExportData } from '@/types/api'

const userStore = useUserStore()
const toast = useToast()

const exporting = ref(false)

const SHARE_TEXT = '我在用 AI 饮食管控教练记录体重健康报告，来看看我的减脂进展吧～'

async function onExport() {
  if (exporting.value) return
  exporting.value = true
  try {
    const data = await exportReport({ report_type: 'weight', format: 'csv' })
    saveCsv(data)
  } catch (e) {
    // 错误信息已由 request 统一 toast
    void e
  } finally {
    exporting.value = false
  }
}

/** 落地 CSV：H5 下载；小程序复制文本（平台能力差异降级） */
function saveCsv(data: ReportExportData) {
  // #ifdef H5
  try {
    const blob = new Blob([`\uFEFF${data.content}`], {
      type: data.mime || 'text/csv;charset=utf-8',
    })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = data.filename || 'weight-report.csv'
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
    toast.success({ title: '已开始下载' })
  } catch (e) {
    void e
    toast.error({ title: '导出失败，请重试' })
  }
  return
  // #endif
  // #ifndef H5
  uni.setClipboardData({
    data: data.content,
    success: () => toast.info({ title: '报告已复制，可粘贴保存' }),
    fail: () => toast.error({ title: '导出失败，请重试' }),
  })
  // #endif
}

/** 分享报告：优先 uni.share，降级复制文案 */
function onShare() {
  const anyUni = uni as unknown as {
    share?: (opts: {
      provider?: string
      scene?: string
      type?: number
      title?: string
      summary?: string
      href?: string
      success?: () => void
      fail?: () => void
    }) => void
  }
  if (typeof anyUni.share === 'function') {
    anyUni.share({
      provider: 'weixin',
      scene: 'WXSceneSession',
      type: 0,
      title: '我的体重健康报告',
      summary: SHARE_TEXT,
      href: '',
      success: () => toast.success({ title: '分享成功' }),
      fail: () => copyShare(),
    })
    return
  }
  copyShare()
}

function copyShare() {
  uni.setClipboardData({
    data: SHARE_TEXT,
    success: () => toast.info({ title: '分享文案已复制' }),
    fail: () => toast.info({ title: '可点击右上角分享给好友' }),
  })
}

function goWeekly() {
  uni.navigateTo({ url: '/pages/report/weekly' })
}

function goLogin() {
  redirectToLogin()
}
</script>

<style lang="scss" scoped>
.rp {
  padding: $space-md;

  &__card {
    margin-bottom: $space-md;
  }

  &__btn-row {
    margin-bottom: $space-sm;
  }

  &__tip {
    display: block;
    margin-top: $space-xs;
    font-size: $t-22;
    color: $text-3;
  }

  &__item {
    @include flex-between;
  }

  &__item-main {
    flex: 1;
    min-width: 0;
  }

  &__item-label {
    display: block;
    font-size: $t-26;
    color: $text-1;
  }

  &__item-desc {
    display: block;
    margin-top: 4rpx;
    font-size: $t-22;
    color: $text-3;
  }

  &__item-arrow {
    flex: none;
    font-size: $t-24;
    color: $text-3;
  }
}
</style>