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
      <template #header>
        <div class="card-header">
          <span>券池列表（券发放唯一源头）</span>
          <el-button type="primary" @click="openCreate">新建券池</el-button>
        </div>
      </template>

      <el-table v-loading="loading" :data="items" stripe>
        <el-table-column prop="id" label="ID" width="64" />
        <el-table-column prop="name" label="券池名称" min-width="150" />
        <el-table-column label="类型" width="90">
          <template #default="{ row }: { row: AdminCouponPoolOut }">
            <el-tag>{{ typeLabel(row.type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="范围" width="90">
          <template #default="{ row }: { row: AdminCouponPoolOut }">
            <el-tag type="info">{{ scopeLabel(row.scope) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="面额" min-width="120">
          <template #default="{ row }: { row: AdminCouponPoolOut }">
            <span v-if="row.type === 2">{{ ((row.discount_rate ?? 0) * 10).toFixed(0) }} 折（率 {{ row.discount_rate }}）</span>
            <span v-else class="money">¥{{ row.amount.toFixed(2) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="门槛" width="90">
          <template #default="{ row }: { row: AdminCouponPoolOut }">
            <span>¥{{ row.min_spend.toFixed(2) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="余量" min-width="170">
          <template #default="{ row }: { row: AdminCouponPoolOut }">
            <el-progress :percentage="pct(row)" :stroke-width="12" striped striped-flow />
            <span class="stock-text">已发 {{ row.granted_count }} / {{ row.total_count }}，剩 {{ row.total_count - row.granted_count }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="170" />
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }: { row: AdminCouponPoolOut }">
            <el-button type="primary" size="small" :disabled="row.granted_count >= row.total_count" @click="openGrant(row)">发放</el-button>
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

    <!-- 新建券池 -->
    <el-dialog v-model="createVisible" title="新建券池" width="560px">
      <el-form label-width="110px">
        <el-form-item label="券池名称" required>
          <el-input v-model="createForm.name" maxlength="64" placeholder="如：新人满减券" />
        </el-form-item>
        <el-form-item label="券类型" required>
          <el-radio-group v-model="createForm.type">
            <el-radio-button :value="1">满减</el-radio-button>
            <el-radio-button :value="2">折扣</el-radio-button>
            <el-radio-button :value="3">免费</el-radio-button>
            <el-radio-button :value="4">体验</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="适用范围" required>
          <el-radio-group v-model="createForm.scope">
            <el-radio-button :value="1">吃</el-radio-button>
            <el-radio-button :value="2">动</el-radio-button>
            <el-radio-button :value="3">异业</el-radio-button>
            <el-radio-button :value="4">通用</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="createForm.scope === 3" label="商家 ID">
          <el-input-number v-model="createForm.merchant_id" :min="1" controls-position="right" placeholder="异业券指定商家" />
        </el-form-item>
        <el-form-item v-if="createForm.type === 2" label="折扣率" required>
          <el-input-number v-model="createForm.discount_rate" :min="0.01" :max="0.99" :step="0.05" controls-position="right" />
          <span class="tip">如 0.8 表示 8 折</span>
        </el-form-item>
        <el-form-item v-if="createForm.type === 1 || createForm.type === 4" label="减免金额">
          <el-input-number v-model="createForm.amount" :min="0" :precision="2" :step="1" controls-position="right" />
          <span class="tip">元</span>
        </el-form-item>
        <el-form-item label="使用门槛">
          <el-input-number v-model="createForm.min_spend" :min="0" :precision="2" controls-position="right" />
          <span class="tip">元，0 表示无门槛</span>
        </el-form-item>
        <el-form-item label="发行总量" required>
          <el-input-number v-model="createForm.total_count" :min="1" controls-position="right" />
        </el-form-item>
        <el-form-item label="有效期">
          <el-date-picker v-model="validRange" type="datetimerange" start-placeholder="生效时间" end-placeholder="失效时间" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="onCreate">创建</el-button>
      </template>
    </el-dialog>

    <!-- 发放 -->
    <el-dialog v-model="grantVisible" title="发放优惠券" width="440px">
      <div class="grant-pool">券池：{{ grantPool?.name }}（剩 {{ grantPool ? grantPool.total_count - grantPool.granted_count : 0 }} 张）</div>
      <el-form label-width="90px">
        <el-form-item label="用户 ID" required>
          <el-input-number v-model="grantForm.user_id" :min="1" controls-position="right" style="width: 180px" />
        </el-form-item>
        <el-form-item label="发放数量">
          <el-input-number v-model="grantForm.count" :min="1" :max="grantMax" controls-position="right" style="width: 180px" />
          <span class="tip">最多 {{ grantMax }} 张（券池余量）</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="grantVisible = false">取消</el-button>
        <el-button type="primary" :loading="granting" @click="onGrant">确认发放</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { createCouponPool, grantCoupon, listCouponPools } from '@/api/admin'
import { isNetworkError } from '@/api/client'
import type { AdminCouponPoolOut } from '@/types/api'

const items = ref<AdminCouponPoolOut[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const isFallback = ref(false)
const error = ref<string | null>(null)

const FALLBACK: AdminCouponPoolOut[] = [
  {
    id: 1,
    name: '新人满减券（ demo ）',
    type: 1,
    scope: 1,
    amount: 10,
    discount_rate: null,
    min_spend: 30,
    merchant_id: null,
    total_count: 1000,
    granted_count: 356,
    valid_from: '2026-09-01T00:00:00+08:00',
    valid_to: '2026-10-01T00:00:00+08:00',
    created_at: '2026-09-01T08:00:00+08:00',
  },
  {
    id: 2,
    name: '轻食 8 折券',
    type: 2,
    scope: 4,
    amount: 0,
    discount_rate: 0.8,
    min_spend: 0,
    merchant_id: null,
    total_count: 500,
    granted_count: 120,
    valid_from: null,
    valid_to: null,
    created_at: '2026-09-10T08:00:00+08:00',
  },
  {
    id: 3,
    name: '健身房体验券',
    type: 4,
    scope: 3,
    amount: 20,
    discount_rate: null,
    min_spend: 0,
    merchant_id: 2,
    total_count: 200,
    granted_count: 200,
    valid_from: null,
    valid_to: null,
    created_at: '2026-09-12T08:00:00+08:00',
  },
]

function typeLabel(t: AdminCouponPoolOut['type']): string {
  return ({ 1: '满减', 2: '折扣', 3: '免费', 4: '体验' })[t] ?? '未知'
}

function scopeLabel(s: AdminCouponPoolOut['scope']): string {
  return ({ 1: '吃', 2: '动', 3: '异业', 4: '通用' })[s] ?? '未知'
}

function pct(row: AdminCouponPoolOut): number {
  if (row.total_count <= 0) return 0
  return Math.min(100, Math.round((row.granted_count / row.total_count) * 100))
}

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const data = await listCouponPools({ page: page.value, page_size: pageSize.value })
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
      error.value = err instanceof Error ? err.message : '券池列表加载失败'
    }
  } finally {
    loading.value = false
  }
}

// ---- 新建券池 ----
const createVisible = ref(false)
const creating = ref(false)
const validRange = ref<[Date, Date] | null>(null)
const createForm = reactive({
  name: '',
  type: 1 as 1 | 2 | 3 | 4,
  scope: 1 as 1 | 2 | 3 | 4,
  amount: 10,
  discount_rate: 0.8,
  min_spend: 0,
  merchant_id: 1,
  total_count: 100,
})

function openCreate(): void {
  createForm.name = ''
  validRange.value = null
  createVisible.value = true
}

function fmtIso(d: Date): string {
  return d.toISOString()
}

async function onCreate(): Promise<void> {
  if (!createForm.name.trim()) {
    ElMessage.warning('请输入券池名称')
    return
  }
  if (createForm.type === 1 && createForm.amount <= 0) {
    ElMessage.warning('满减券的减免金额需大于 0')
    return
  }
  if (createForm.total_count < 1) {
    ElMessage.warning('发行总量至少为 1')
    return
  }
  creating.value = true
  try {
    await createCouponPool({
      name: createForm.name.trim(),
      type: createForm.type,
      scope: createForm.scope,
      amount: createForm.type === 1 || createForm.type === 4 ? createForm.amount : 0,
      discount_rate: createForm.type === 2 ? createForm.discount_rate : null,
      min_spend: createForm.min_spend,
      merchant_id: createForm.scope === 3 ? createForm.merchant_id : null,
      total_count: createForm.total_count,
      valid_from: validRange.value ? fmtIso(validRange.value[0]) : null,
      valid_to: validRange.value ? fmtIso(validRange.value[1]) : null,
    })
    ElMessage.success('券池已创建')
    createVisible.value = false
    page.value = 1 // 回到首页，确保新券池可见
  } catch (err) {
    if (isNetworkError(err)) {
      ElMessage.warning('后端未连接，已本地模拟创建')
    }
  } finally {
    creating.value = false
    await load()
  }
}

// ---- 发放 ----
const grantVisible = ref(false)
const granting = ref(false)
const grantPool = ref<AdminCouponPoolOut | null>(null)
const grantForm = reactive({ user_id: 1, count: 1 })

/** 券池剩余可发放张数：发放数量上限，避免超额发放 */
const grantMax = computed(() => {
  const p = grantPool.value
  if (!p) return 1
  return Math.max(1, p.total_count - p.granted_count)
})

function openGrant(row: AdminCouponPoolOut): void {
  grantPool.value = row
  grantForm.user_id = 1
  grantForm.count = 1
  grantVisible.value = true
}

async function onGrant(): Promise<void> {
  const pool = grantPool.value
  if (!pool) return
  const remaining = pool.total_count - pool.granted_count
  if (grantForm.count < 1) {
    ElMessage.warning('发放数量至少为 1')
    return
  }
  if (grantForm.count > remaining) {
    ElMessage.warning(`发放数量超出券池余量（剩余 ${remaining} 张）`)
    return
  }
  try {
    await ElMessageBox.confirm(
      `确认向用户 ${grantForm.user_id} 发放「${pool.name}」${grantForm.count} 张？`,
      '发放确认',
      { confirmButtonText: '确认发放', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return // 用户取消
  }
  granting.value = true
  try {
    const data = await grantCoupon({
      pool_id: pool.id,
      user_id: grantForm.user_id,
      count: grantForm.count,
    })
    ElMessage.success(`已向用户 ${data.user_id ?? grantForm.user_id} 发放 ${data.granted_count} 张券`)
    grantVisible.value = false
  } catch (err) {
    if (isNetworkError(err)) {
      ElMessage.warning('后端未连接，已本地模拟发放')
    }
    // 余量不足 4001 等业务错误已由拦截器弹出后端 message
  } finally {
    granting.value = false
    await load()
  }
}

onMounted(load)
</script>

<style scoped>
.retry-btn {
  margin-left: 8px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.pager {
  margin-top: 16px;
  justify-content: flex-end;
}

.stock-text {
  font-size: 12px;
  color: #6b7280;
}

.tip {
  margin-left: 8px;
  font-size: 12px;
  color: #9ca3af;
}

.grant-pool {
  margin-bottom: 16px;
  font-size: 13px;
  color: #374151;
}
</style>
