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
        <el-tab-pane label="待支付" name="1" />
        <el-tab-pane label="已支付待核销" name="2" />
        <el-tab-pane label="已完成" name="3" />
        <el-tab-pane label="已取消" name="4" />
        <el-tab-pane label="已退款" name="5" />
      </el-tabs>

      <el-alert
        v-if="isMerchantRole"
        title="商家角色：已自动限定为本商家订单"
        type="info"
        show-icon
        :closable="false"
        class="fallback-alert"
      />

      <el-table v-loading="loading" :data="items" stripe>
        <el-table-column prop="id" label="ID" width="64" />
        <el-table-column prop="order_no" label="订单号" min-width="180" />
        <el-table-column label="商家" min-width="140">
          <template #default="{ row }: { row: OrderBrief }">
            {{ row.merchant_name ?? `商家 #${row.merchant_id}` }}
          </template>
        </el-table-column>
        <el-table-column label="总额" width="100">
          <template #default="{ row }: { row: OrderBrief }">
            <span>¥{{ row.total_amount.toFixed(2) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="优惠" width="100">
          <template #default="{ row }: { row: OrderBrief }">
            <span style="color: #ef4444">-¥{{ row.discount_amount.toFixed(2) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="实付" width="110">
          <template #default="{ row }: { row: OrderBrief }">
            <span class="money">¥{{ row.pay_amount.toFixed(2) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }: { row: OrderBrief }">
            <el-tag :type="statusTagType(row.status)">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="核销码" width="120">
          <template #default="{ row }: { row: OrderBrief }">
            {{ row.redeem_code ?? '-' }}
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="下单时间" width="170" />
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
import { listOrders } from '@/api/admin'
import { isNetworkError } from '@/api/client'
import { getAuth } from '@/composables/auth'
import type { OrderBrief, OrderStatus } from '@/types/api'

const auth = getAuth()
const isMerchantRole = auth?.role === 3

const items = ref<OrderBrief[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const activeTab = ref<'all' | '1' | '2' | '3' | '4' | '5'>('all')
const loading = ref(false)
const isFallback = ref(false)
const error = ref<string | null>(null)

const FALLBACK: OrderBrief[] = [
  {
    id: 1,
    order_no: 'OC20260929001',
    merchant_id: 1,
    merchant_name: '绿野轻食（ demo ）',
    total_amount: 66,
    discount_amount: 10,
    pay_amount: 56,
    status: 2,
    redeem_code: 'R8K2QM',
    expire_at: '2026-09-29T21:00:00+08:00',
    created_at: '2026-09-29T12:10:00+08:00',
  },
  {
    id: 2,
    order_no: 'OC20260929002',
    merchant_id: 2,
    merchant_name: '果燃酸奶茶饮',
    total_amount: 25,
    discount_amount: 0,
    pay_amount: 25,
    status: 3,
    redeem_code: 'T1N9PL',
    expire_at: null,
    created_at: '2026-09-29T11:05:00+08:00',
  },
  {
    id: 3,
    order_no: 'OC20260929003',
    merchant_id: 1,
    merchant_name: null,
    total_amount: 42,
    discount_amount: 8.4,
    pay_amount: 33.6,
    status: 1,
    redeem_code: null,
    expire_at: '2026-09-29T23:59:59+08:00',
    created_at: '2026-09-29T10:32:00+08:00',
  },
]

function statusLabel(s: OrderStatus): string {
  return ({ 1: '待支付', 2: '已支付待核销', 3: '已完成', 4: '已取消', 5: '已退款' })[s] ?? '未知'
}

function statusTagType(s: OrderStatus): 'warning' | 'primary' | 'success' | 'info' | 'danger' | undefined {
  return ({ 1: 'warning', 2: 'primary', 3: 'success', 4: 'info', 5: 'danger' } as const)[s] ?? 'info'
}

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const params: { status?: number; merchant_id?: number; page: number; page_size: number } = {
      page: page.value,
      page_size: pageSize.value,
    }
    if (activeTab.value !== 'all') {
      params.status = Number(activeTab.value)
    }
    // 商家角色自动限定本商家
    if (isMerchantRole && auth?.merchant_id) {
      params.merchant_id = auth.merchant_id
    }
    const data = await listOrders(params)
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
      error.value = err instanceof Error ? err.message : '订单列表加载失败'
    }
  } finally {
    loading.value = false
  }
}

function onTabChange(): void {
  page.value = 1
  load()
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
</style>
