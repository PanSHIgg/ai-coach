<template>
  <div>
    <el-alert
      v-if="isFallback"
      title="后端未连接，展示演示数据"
      type="warning"
      show-icon
      :closable="false"
      class="fallback-alert"
    />

    <el-alert v-if="error" type="error" show-icon :closable="false" class="fallback-alert">
      <template #title>
        <span>{{ error }}</span>
        <el-button link type="primary" size="small" class="retry-btn" @click="load">重试</el-button>
      </template>
    </el-alert>

    <el-card class="page-card">
      <el-tabs v-model="activeTab" @tab-change="onTabChange">
        <el-tab-pane label="全部" name="all" />
        <el-tab-pane label="待审" name="0" />
        <el-tab-pane label="已通过" name="1" />
        <el-tab-pane label="已驳回" name="2" />
      </el-tabs>

      <el-table v-loading="loading" :data="items" stripe>
        <el-table-column prop="id" label="ID" width="64" />
        <el-table-column label="类型" width="90">
          <template #default="{ row }: { row: AdminAuditItem }">
            <el-tag :type="targetTagType(row.target_type)">{{ targetLabel(row.target_type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="target_id" label="对象ID" width="90" />
        <el-table-column prop="nickname" label="提交者" width="120" />
        <el-table-column
          prop="content_snapshot"
          label="内容快照"
          min-width="220"
          show-overflow-tooltip
        />
        <el-table-column label="安全判定" width="100">
          <template #default="{ row }: { row: AdminAuditItem }">
            {{ secLabel(row.sec_check_result) }}
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }: { row: AdminAuditItem }">
            <el-tag :type="statusTagType(row.status)">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="提交时间" width="170" />
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }: { row: AdminAuditItem }">
            <template v-if="row.status === 0">
              <el-button type="primary" size="small" @click="onReview(row, 1)">通过</el-button>
              <el-button type="danger" size="small" @click="onReview(row, 2)">驳回</el-button>
            </template>
            <span v-else-if="row.reject_reason" class="reason">原因：{{ row.reject_reason }}</span>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="total"
        :page-sizes="[10, 20, 50]"
        layout="total, sizes, prev, pager, next"
        class="pager"
        @change="load"
      />
    </el-card>
  </div>
</template>

<script setup lang="ts">
/**
 * ADM · 内容审核队列 — Phase 4 (M4)
 * 契约：GET /api/admin/audit/list、POST /api/admin/audit/{id}/review（1通过 2驳回）
 * 依据：plan.md §10 Track ADM（违规内容处理）
 */
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { listAudit, reviewAudit } from '@/api/admin'
import { isNetworkError } from '@/api/client'
import type { AdminAuditItem } from '@/types/api'

const items = ref<AdminAuditItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const activeTab = ref<'all' | '0' | '1' | '2'>('all')
const loading = ref(false)
const isFallback = ref(false)
const error = ref<string | null>(null)

const FALLBACK: AdminAuditItem[] = [
  {
    id: 1,
    target_type: 1,
    target_id: 2,
    user_id: 1001,
    nickname: '减友A',
    content_snapshot: '这是违规词内容',
    sec_check_result: 3,
    status: 0,
    reject_reason: null,
    reviewer_id: null,
    reviewed_at: null,
    created_at: '2026-09-29T10:00:00+08:00',
  },
]

const TARGET_LABEL: Record<number, string> = { 1: '动态', 2: '评论', 3: '图片', 4: '商家入驻' }
const TARGET_TAG: Record<number, 'primary' | 'success' | 'warning' | 'info'> = {
  1: 'primary',
  2: 'success',
  3: 'warning',
  4: 'info',
}

function targetLabel(t: number): string {
  return TARGET_LABEL[t] ?? '其他'
}

function targetTagType(t: number): 'primary' | 'success' | 'warning' | 'info' {
  return TARGET_TAG[t] ?? 'info'
}

function secLabel(s: number | null): string {
  return ({ 1: '通过', 2: '可疑', 3: '不通过' } as Record<number, string>)[s ?? 0] ?? '—'
}

function statusLabel(s: number): string {
  return ({ 0: '待审', 1: '已通过', 2: '已驳回' } as Record<number, string>)[s] ?? '未知'
}

function statusTagType(s: number): 'warning' | 'success' | 'danger' | 'info' {
  return ({ 0: 'warning', 1: 'success', 2: 'danger' } as Record<number, 'warning' | 'success' | 'danger'>)[s] ?? 'info'
}

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const params: { status?: number; page: number; page_size: number } = {
      page: page.value,
      page_size: pageSize.value,
    }
    if (activeTab.value !== 'all') {
      params.status = Number(activeTab.value)
    }
    const data = await listAudit(params)
    items.value = data.items
    total.value = data.page.total
    isFallback.value = false
  } catch (err) {
    if (isNetworkError(err)) {
      items.value = FALLBACK
      total.value = FALLBACK.length
      isFallback.value = true
    } else {
      items.value = []
      total.value = 0
      isFallback.value = false
      error.value = err instanceof Error ? err.message : '审核队列加载失败'
    }
  } finally {
    loading.value = false
  }
}

/** 切换筛选 tab 时回到第 1 页，避免分页越界导致空白页 */
function onTabChange(): void {
  page.value = 1
  load()
}

async function onReview(row: AdminAuditItem, status: 1 | 2): Promise<void> {
  try {
    if (status === 1) {
      await ElMessageBox.confirm(`确认通过该${targetLabel(row.target_type)}内容？`, '审核确认', {
        confirmButtonText: '确认通过',
        cancelButtonText: '取消',
        type: 'success',
      })
      await doReview(row.id, 1, null)
      return
    }
    const { value } = await ElMessageBox.prompt('请输入驳回原因', '驳回审核', {
      confirmButtonText: '确认驳回',
      cancelButtonText: '取消',
      inputPlaceholder: '驳回原因（必填，最多 200 字）',
      inputValidator: (v: string) => (v && v.trim().length > 0 ? true : '驳回原因不能为空'),
    })
    await doReview(row.id, 2, value?.trim() ?? '')
  } catch {
    // 用户取消弹窗
  }
}

async function doReview(id: number, status: 1 | 2, reason: string | null): Promise<void> {
  try {
    await reviewAudit(id, { status, reason })
    ElMessage.success(status === 1 ? '已通过' : '已驳回')
  } catch (err) {
    if (isNetworkError(err)) {
      ElMessage.warning('后端未连接，本地模拟审核成功')
    }
  }
  await load()
}

onMounted(load)
</script>

<style scoped>
.retry-btn {
  margin-left: 8px;
}

.pager {
  margin-top: 16px;
  justify-content: flex-end;
}

.reason {
  font-size: 12px;
  color: #9ca3af;
}
</style>
