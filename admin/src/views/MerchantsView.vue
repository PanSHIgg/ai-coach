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
        <el-tab-pane label="待审核" name="0" />
        <el-tab-pane label="已通过" name="1" />
        <el-tab-pane label="已驳回" name="2" />
      </el-tabs>

      <el-table v-loading="loading" :data="items" stripe>
        <el-table-column prop="id" label="ID" width="64" />
        <el-table-column prop="name" label="商家名称" min-width="140" />
        <el-table-column prop="category" label="品类" width="90" />
        <el-table-column prop="address" label="地址" min-width="200" show-overflow-tooltip />
        <el-table-column prop="rating" label="评分" width="80" />
        <el-table-column label="营业状态" width="90">
          <template #default="{ row }: { row: AdminMerchantOut }">
            <el-tag :type="row.status === 1 ? 'success' : 'info'">{{ row.status === 1 ? '营业' : '停业' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="审核状态" width="100">
          <template #default="{ row }: { row: AdminMerchantOut }">
            <el-tag :type="auditTagType(row.audit_status)">{{ auditLabel(row.audit_status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="入驻时间" width="170" />
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }: { row: AdminMerchantOut }">
            <template v-if="row.audit_status === 0">
              <el-button type="primary" size="small" @click="onAudit(row, 1)">通过</el-button>
              <el-button type="danger" size="small" @click="onAudit(row, 2)">驳回</el-button>
            </template>
            <span v-else-if="row.audit_reason" class="reason">原因：{{ row.audit_reason }}</span>
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
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { auditMerchant, listMerchants } from '@/api/admin'
import { isNetworkError } from '@/api/client'
import type { AdminMerchantOut } from '@/types/api'

const items = ref<AdminMerchantOut[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const activeTab = ref<'all' | '0' | '1' | '2'>('all')
const loading = ref(false)
const isFallback = ref(false)
const error = ref<string | null>(null)

const FALLBACK: AdminMerchantOut[] = [
  {
    id: 1,
    name: '绿野轻食（ demo ）',
    category: '轻食',
    address: '上海市浦东新区张江路 88 号',
    phone: '13800000001',
    lat: 31.2,
    lng: 121.6,
    rating: 4.8,
    cover_url: null,
    status: 1,
    audit_status: 0,
    audit_reason: null,
    owner_user_id: 101,
    created_at: '2026-09-20T10:00:00+08:00',
  },
  {
    id: 2,
    name: '果燃酸奶茶饮',
    category: '茶饮',
    address: '上海市徐汇区漕溪北路 66 号',
    phone: '13800000002',
    lat: 31.19,
    lng: 121.44,
    rating: 4.5,
    cover_url: null,
    status: 1,
    audit_status: 1,
    audit_reason: null,
    owner_user_id: 102,
    created_at: '2026-09-18T14:30:00+08:00',
  },
  {
    id: 3,
    name: ' power 健身餐',
    category: '健身餐',
    address: '北京市朝阳区望京 SOHO T1',
    phone: null,
    lat: 39.99,
    lng: 116.48,
    rating: 4.2,
    cover_url: null,
    status: 0,
    audit_status: 2,
    audit_reason: '资质照片模糊，请重新上传',
    owner_user_id: 103,
    created_at: '2026-09-15T09:00:00+08:00',
  },
]

function auditLabel(s: AdminMerchantOut['audit_status']): string {
  return ({ 0: '待审核', 1: '已通过', 2: '已驳回' })[s] ?? '未知'
}

function auditTagType(s: AdminMerchantOut['audit_status']): 'warning' | 'success' | 'danger' | 'info' {
  return ({ 0: 'warning', 1: 'success', 2: 'danger' } as const)[s] ?? 'info'
}

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const params: { audit_status?: number; page: number; page_size: number } = {
      page: page.value,
      page_size: pageSize.value,
    }
    if (activeTab.value !== 'all') {
      params.audit_status = Number(activeTab.value)
    }
    const data = await listMerchants(params)
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
      error.value = err instanceof Error ? err.message : '商家列表加载失败'
    }
  } finally {
    loading.value = false
  }
}

/** 切换筛选 tab 时回到第 1 页，避免第 3 页 × 新筛选条件导致空白页 */
function onTabChange(): void {
  page.value = 1
  load()
}

async function onAudit(row: AdminMerchantOut, auditStatus: 1 | 2): Promise<void> {
  try {
    if (auditStatus === 1) {
      await ElMessageBox.confirm(`确认通过商家「${row.name}」的入驻申请？`, '审核确认', {
        confirmButtonText: '确认通过',
        cancelButtonText: '取消',
        type: 'success',
      })
      await doAudit(row, 1, null)
      return
    }
    const { value } = await ElMessageBox.prompt(`请输入驳回「${row.name}」的原因`, '驳回审核', {
      confirmButtonText: '确认驳回',
      cancelButtonText: '取消',
      inputPlaceholder: '驳回原因（必填，最多 200 字）',
      inputValidator: (v: string) => (v && v.trim().length > 0 ? true : '驳回原因不能为空'),
    })
    await doAudit(row, 2, value?.trim() ?? '')
  } catch {
    // 用户取消弹窗
  }
}

async function doAudit(row: AdminMerchantOut, auditStatus: 1 | 2, reason: string | null): Promise<void> {
  try {
    await auditMerchant(row.id, { audit_status: auditStatus, reason })
    ElMessage.success(auditStatus === 1 ? '已通过' : '已驳回')
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
