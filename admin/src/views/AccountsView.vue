<template>
  <div>
    <el-alert v-if="error" type="error" show-icon :closable="false" class="fallback-alert">
      <template #title>
        <span>{{ error }}</span>
        <el-button link type="primary" size="small" class="retry-btn" @click="load">重试</el-button>
      </template>
    </el-alert>

    <el-card class="page-card">
      <template #header>
        <div class="card-header">
          <span>后台账号（超管可建运营 / 商家，运营仅可建商家账号；教练账号走教练端）</span>
          <el-button type="primary" @click="openCreate">新建账号</el-button>
        </div>
      </template>

      <el-table v-loading="loading" :data="items" stripe>
        <el-table-column prop="id" label="ID" width="64" />
        <el-table-column prop="username" label="账号" min-width="140" />
        <el-table-column label="角色" width="100">
          <template #default="{ row }: { row: AdminAccountOut }">
            <el-tag :type="roleTagType(row.role)">{{ roleText(row.role) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="绑定商家" min-width="140">
          <template #default="{ row }: { row: AdminAccountOut }">
            <span>{{ merchantName(row.merchant_id) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="180">
          <template #default="{ row }: { row: AdminAccountOut }">
            <span>{{ formatTime(row.created_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }: { row: AdminAccountOut }">
            <el-button
              size="small"
              :disabled="!canReset(row)"
              @click="openReset(row)"
            >重置密码</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :page-sizes="[10, 20, 50]"
        :total="total"
        layout="total, sizes, prev, pager, next"
        class="pager"
        @change="load"
      />
    </el-card>

    <!-- 新建账号 -->
    <el-dialog v-model="createVisible" title="新建账号" width="560px">
      <el-form label-width="100px">
        <el-form-item label="账号" required>
          <el-input v-model="form.username" maxlength="64" placeholder="2-64 位，唯一" />
        </el-form-item>
        <el-form-item label="初始密码" required>
          <el-input
            v-model="form.password"
            type="password"
            show-password
            maxlength="128"
            placeholder="≥12 位；占位串/公开口令会被拒绝"
          />
        </el-form-item>
        <el-form-item label="角色" required>
          <el-select v-model="form.role" style="width: 100%">
            <el-option v-if="isSuper" label="运营" :value="2" />
            <el-option label="商家" :value="3" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="form.role === 3" label="绑定商家" required>
          <el-select
            v-model="form.merchantId"
            filterable
            style="width: 100%"
            placeholder="选择商家（已审核通过的商家列表）"
          >
            <el-option
              v-for="m in merchants"
              :key="m.id"
              :label="`${m.name}（${m.audit_status === 1 ? '已过审' : '未过审'}）`"
              :value="m.id"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="onCreate">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createAccount,
  listAccounts,
  listMerchants,
  resetAccountPassword,
} from '@/api/admin'
import { isNetworkError } from '@/api/client'
import { getAuth } from '@/composables/auth'
import type { AdminAccountIn, AdminAccountOut, AdminMerchantOut } from '@/types/api'

const items = ref<AdminAccountOut[]>([])
const merchants = ref<AdminMerchantOut[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)

const auth = getAuth()
const isSuper = (auth?.role ?? 0) === 1

const createVisible = ref(false)
const submitting = ref(false)
// role 类型与契约 AdminAccountIn['role'] 一致（1超管/2运营/3商家）；下拉只给 2/3，
// 超管也不能建 4（教练走 G1 教练端），故超管文案不含「全部角色」。
const form = reactive({
  username: '',
  password: '',
  role: 3 as AdminAccountIn['role'],
  merchantId: null as number | null,
})

function roleText(role: number): string {
  return { 1: '超管', 2: '运营', 3: '商家', 4: '教练' }[role] ?? '未知'
}

function roleTagType(role: number): 'danger' | 'warning' | 'success' | 'info' {
  const map: Record<number, 'danger' | 'warning' | 'success' | 'info'> = {
    1: 'danger',
    2: 'warning',
    3: 'success',
  }
  return map[role] ?? 'info'
}

function merchantName(merchantId: number | null): string {
  if (merchantId == null) return '-'
  const m = merchants.value.find((x) => x.id === merchantId)
  return m ? m.name : `#${merchantId}`
}

function formatTime(value: string): string {
  return value ? value.replace('T', ' ').slice(0, 19) : '-'
}

/** 重置密码：超管任意账号；运营仅商家账号（与后端权限矩阵一致，前端同步隐藏入口） */
function canReset(row: AdminAccountOut): boolean {
  return isSuper || row.role === 3
}

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const data = await listAccounts({ page: page.value, page_size: pageSize.value })
    items.value = data.items
    total.value = data.page.total
  } catch (e) {
    error.value = isNetworkError(e) ? '无法连接后端服务' : (e as Error).message
  } finally {
    loading.value = false
  }
}

/** 商家下拉数据源（创建商家账号时绑定）；复用商家列表接口 */
async function loadMerchants(): Promise<void> {
  try {
    const data = await listMerchants({ page: 1, page_size: 100 })
    merchants.value = data.items
  } catch {
    merchants.value = []
  }
}

function openCreate(): void {
  form.username = ''
  form.password = ''
  form.role = 3
  form.merchantId = null
  createVisible.value = true
  void loadMerchants()
}

async function onCreate(): Promise<void> {
  if (!form.username || form.username.length < 2) {
    ElMessage.warning('请输入账号（至少 2 位）')
    return
  }
  if (form.password.length < 12) {
    ElMessage.warning('初始密码至少 12 位')
    return
  }
  if (form.role === 3 && form.merchantId == null) {
    ElMessage.warning('商家账号必须绑定商家')
    return
  }
  submitting.value = true
  try {
    await createAccount({
      username: form.username,
      password: form.password,
      role: form.role,
      merchant_id: form.role === 3 ? form.merchantId : null,
    })
    ElMessage.success(`账号 ${form.username} 已创建`)
    createVisible.value = false
    await load()
  } catch (e) {
    // 业务错误（2001 重名/弱口令、1002 无权限）已由拦截器统一弹出
    if (isNetworkError(e)) ElMessage.error('无法连接后端服务')
  } finally {
    submitting.value = false
  }
}

async function openReset(row: AdminAccountOut): Promise<void> {
  let newPassword: string
  try {
    const res = await ElMessageBox.prompt(
      `为账号「${row.username}」设置新密码（≥12 位，创建者需线下告知对方）`,
      '重置密码',
      { inputPattern: /^.{12,128}$/, inputErrorMessage: '密码至少 12 位', type: 'warning' },
    )
    newPassword = res.value
  } catch {
    return // 用户取消
  }
  try {
    await resetAccountPassword(row.id, { new_password: newPassword })
    ElMessage.success(`账号 ${row.username} 的密码已重置`)
  } catch (e) {
    if (isNetworkError(e)) ElMessage.error('无法连接后端服务')
  }
}

onMounted(load)
</script>

<style scoped>
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.pager {
  margin-top: 16px;
  justify-content: flex-end;
}
</style>
