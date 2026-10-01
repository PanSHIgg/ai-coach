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
          <span>标准目录（平台运营维护，商家只选不建）</span>
          <div class="header-actions">
            <el-input
              v-model="categoryFilter"
              placeholder="按品类筛选"
              clearable
              style="width: 180px"
              @change="load"
            />
            <el-button type="primary" @click="openCreate">新建目录项</el-button>
          </div>
        </div>
      </template>

      <el-table v-loading="loading" :data="items" stripe>
        <el-table-column prop="id" label="ID" width="64" />
        <el-table-column prop="code" label="编码" width="110" />
        <el-table-column prop="name" label="名称" min-width="140" />
        <el-table-column prop="category" label="品类" width="120" />
        <el-table-column label="热量区间(kcal)" width="150">
          <template #default="{ row }: { row: CatalogItem }">
            <span>{{ row.calories_low ?? '-' }} ~ {{ row.calories_high ?? '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="基准价" width="100">
          <template #default="{ row }: { row: CatalogItem }">
            <span class="money">¥{{ row.base_price.toFixed(2) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="限价区间" width="150">
          <template #default="{ row }: { row: CatalogItem }">
            <span>¥{{ row.min_price.toFixed(2) }} - ¥{{ row.max_price.toFixed(2) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="unit" label="单位" width="80" />
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }: { row: CatalogItem }">
            <el-button type="primary" size="small" @click="openEdit(row)">编辑</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 新建 / 编辑目录项 -->
    <el-dialog v-model="formVisible" :title="editingId ? '编辑目录项' : '新建目录项'" width="600px">
      <el-form label-width="120px">
        <el-form-item label="编码" required>
          <el-input v-model="form.code" maxlength="32" placeholder="如：FD-001" />
        </el-form-item>
        <el-form-item label="名称" required>
          <el-input v-model="form.name" maxlength="128" placeholder="如：鸡胸肉沙拉" />
        </el-form-item>
        <el-form-item label="品类">
          <el-input v-model="form.category" maxlength="64" placeholder="如：标准减脂餐" />
        </el-form-item>
        <el-form-item label="热量区间">
          <el-input-number v-model="form.calories_low" :min="0" controls-position="right" placeholder="下限" />
          <span class="tip">~</span>
          <el-input-number v-model="form.calories_high" :min="0" controls-position="right" placeholder="上限" />
          <span class="tip">kcal</span>
        </el-form-item>
        <el-form-item label="基准价" required>
          <el-input-number v-model="form.base_price" :min="0" :precision="2" :step="1" controls-position="right" />
          <span class="tip">元</span>
        </el-form-item>
        <el-form-item label="限价下限" required>
          <el-input-number v-model="form.min_price" :min="0" :precision="2" :step="1" controls-position="right" />
          <span class="tip">元</span>
        </el-form-item>
        <el-form-item label="限价上限" required>
          <el-input-number v-model="form.max_price" :min="0" :precision="2" :step="1" controls-position="right" />
          <span class="tip">须满足 下限 ≤ 基准价 ≤ 上限</span>
        </el-form-item>
        <el-form-item label="单位">
          <el-input v-model="form.unit" maxlength="32" placeholder="如：份 / 盒" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="formVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="onSubmit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { createSkuCatalog, getSkuCatalog, updateSkuCatalog } from '@/api/admin'
import { isNetworkError } from '@/api/client'
import type { AdminSkuCatalogIn, CatalogItem } from '@/types/api'

const items = ref<CatalogItem[]>([])
const loading = ref(false)
const isFallback = ref(false)
const error = ref<string | null>(null)
const categoryFilter = ref('')

const FALLBACK: CatalogItem[] = [
  { id: 1, code: 'FD-001', name: '低脂鸡胸沙拉', category: '标准减脂餐', calories_low: 250, calories_high: 400, base_price: 28, min_price: 22, max_price: 38, unit: '份' },
  { id: 2, code: 'FD-002', name: '杂粮饭套餐', category: '标准减脂餐', calories_low: 450, calories_high: 650, base_price: 32, min_price: 25, max_price: 42, unit: '份' },
]

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const data = await getSkuCatalog(categoryFilter.value.trim() || undefined)
    items.value = data.items
    isFallback.value = false
  } catch (err) {
    if (isNetworkError(err)) {
      items.value = FALLBACK
      isFallback.value = true
    } else {
      items.value = []
      isFallback.value = false
      error.value = err instanceof Error ? err.message : '标准目录加载失败'
    }
  } finally {
    loading.value = false
  }
}

// ---- 新建 / 编辑 ----
const formVisible = ref(false)
const submitting = ref(false)
const editingId = ref<number | null>(null)
const form = reactive({
  code: '',
  name: '',
  category: '',
  calories_low: undefined as number | undefined,
  calories_high: undefined as number | undefined,
  base_price: 0,
  min_price: 0,
  max_price: 0,
  unit: '',
})

function resetForm(): void {
  form.code = ''
  form.name = ''
  form.category = ''
  form.calories_low = undefined
  form.calories_high = undefined
  form.base_price = 0
  form.min_price = 0
  form.max_price = 0
  form.unit = ''
}

function openCreate(): void {
  editingId.value = null
  resetForm()
  formVisible.value = true
}

function openEdit(row: CatalogItem): void {
  editingId.value = row.id
  form.code = row.code
  form.name = row.name
  form.category = row.category ?? ''
  form.calories_low = row.calories_low ?? undefined
  form.calories_high = row.calories_high ?? undefined
  form.base_price = row.base_price
  form.min_price = row.min_price
  form.max_price = row.max_price
  form.unit = row.unit ?? ''
  formVisible.value = true
}

async function onSubmit(): Promise<void> {
  if (!form.code.trim()) {
    ElMessage.warning('请输入编码')
    return
  }
  if (!form.name.trim()) {
    ElMessage.warning('请输入名称')
    return
  }
  if (!(form.min_price <= form.base_price && form.base_price <= form.max_price)) {
    ElMessage.warning('价格区间需满足 下限 ≤ 基准价 ≤ 上限')
    return
  }
  const payload: AdminSkuCatalogIn = {
    code: form.code.trim(),
    name: form.name.trim(),
    category: form.category.trim() || null,
    calories_low: form.calories_low ?? null,
    calories_high: form.calories_high ?? null,
    base_price: form.base_price,
    min_price: form.min_price,
    max_price: form.max_price,
    unit: form.unit.trim() || null,
  }
  submitting.value = true
  try {
    if (editingId.value) {
      await updateSkuCatalog(editingId.value, payload)
      ElMessage.success('目录项已更新')
    } else {
      await createSkuCatalog(payload)
      ElMessage.success('目录项已创建')
    }
    formVisible.value = false
  } catch (err) {
    if (isNetworkError(err)) {
      ElMessage.warning('后端未连接，已本地模拟保存')
      formVisible.value = false
    }
    // 重名 2001 等业务错误已由拦截器弹出后端 message
  } finally {
    submitting.value = false
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
  gap: 8px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.tip {
  margin: 0 6px;
  font-size: 12px;
  color: #9ca3af;
}

.money {
  color: #16a34a;
}
</style>