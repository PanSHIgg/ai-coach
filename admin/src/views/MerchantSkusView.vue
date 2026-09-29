<template>
  <div>
    <el-alert
      v-if="catalogFallback"
      :title="'后端未连接，目录下拉为演示数据'"
      type="warning"
      show-icon
      :closable="false"
      class="fallback-alert"
    />

    <el-alert v-if="catalogError" type="error" show-icon :closable="false" class="fallback-alert">
      <template #title>
        <span>{{ catalogError }}</span>
        <el-button link type="primary" size="small" class="retry-btn" @click="loadCatalog">重试</el-button>
      </template>
    </el-alert>

    <el-row :gutter="16">
      <el-col :md="12" :xs="24">
        <el-card class="page-card" header="商家选品定价">
          <el-form label-width="110px">
            <el-form-item label="商家 ID" required>
              <el-input-number v-model="form.merchant_id" :min="1" controls-position="right" style="width: 200px" />
            </el-form-item>
            <el-form-item label="标准目录" required>
              <el-select v-loading="catalogLoading" v-model="form.catalog_id" placeholder="请选择标准 SKU" style="width: 100%" @change="onCatalogChange">
                <el-option
                  v-for="c in catalog"
                  :key="c.id"
                  :value="c.id"
                  :label="`${c.code} ${c.name}`"
                />
              </el-select>
              <div v-if="selectedCatalog" class="range-tip">
                目录限价区间：¥{{ selectedCatalog.min_price }} - ¥{{ selectedCatalog.max_price }}（基准价 ¥{{ selectedCatalog.base_price }}）
              </div>
            </el-form-item>
            <el-form-item label="售价（元）" required>
              <el-input-number v-model="form.price" :min="0" :precision="2" :step="0.5" controls-position="right" style="width: 200px" />
            </el-form-item>
            <el-form-item label="库存">
              <el-input-number v-model="form.stock" :min="-1" controls-position="right" style="width: 200px" />
              <span class="range-tip" style="margin-left: 8px">-1 表示不限量</span>
            </el-form-item>
            <el-form-item label="状态">
              <el-radio-group v-model="form.status">
                <el-radio :value="1">上架</el-radio>
                <el-radio :value="0">下架</el-radio>
              </el-radio-group>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="submitting" @click="onSubmit">提交选品定价</el-button>
            </el-form-item>
          </el-form>

          <el-alert v-if="lastError" :title="lastError" type="warning" show-icon :closable="true" @close="lastError = null" />
        </el-card>
      </el-col>

      <el-col :md="12" :xs="24">
        <el-card class="page-card" header="最近一次提交结果（后端回显）">
          <el-empty v-if="!result" description="尚未提交" />
          <template v-else>
            <el-descriptions :column="1" border>
              <el-descriptions-item label="商家 SKU ID">{{ result.id }}</el-descriptions-item>
              <el-descriptions-item label="商家">{{ result.merchant_name ?? result.merchant_id }}</el-descriptions-item>
              <el-descriptions-item label="目录">{{ result.catalog_code }} {{ result.catalog_name }}</el-descriptions-item>
              <el-descriptions-item label="售价">
                <span class="money">¥{{ result.price.toFixed(2) }}</span>
              </el-descriptions-item>
              <el-descriptions-item label="限价区间">¥{{ result.min_price }} - ¥{{ result.max_price }}</el-descriptions-item>
              <el-descriptions-item label="库存">{{ result.stock === -1 ? '不限量' : result.stock }}</el-descriptions-item>
              <el-descriptions-item label="状态">{{ result.status === 1 ? '上架' : '下架' }}</el-descriptions-item>
            </el-descriptions>
          </template>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getSkuCatalog, upsertMerchantSku } from '@/api/admin'
import { isNetworkError } from '@/api/client'
import type { AdminMerchantSkuData, CatalogItem } from '@/types/api'

const catalog = ref<CatalogItem[]>([])
const catalogFallback = ref(false)
const catalogError = ref<string | null>(null)
const catalogLoading = ref(false)
const form = reactive({
  merchant_id: 1,
  catalog_id: undefined as number | undefined,
  price: 0,
  stock: -1,
  status: 1 as 0 | 1,
})
const submitting = ref(false)
const lastError = ref<string | null>(null)
const result = ref<AdminMerchantSkuData | null>(null)

const FALLBACK_CATALOG: CatalogItem[] = [
  { id: 1, code: 'FD-001', name: '低脂鸡胸沙拉', category: '轻食', calories_low: 250, calories_high: 400, base_price: 28, min_price: 22, max_price: 38, unit: '份' },
  { id: 2, code: 'FD-002', name: '杂粮饭套餐', category: '主食', calories_low: 450, calories_high: 650, base_price: 32, min_price: 25, max_price: 42, unit: '份' },
  { id: 3, code: 'SP-001', name: '无糖酸奶', category: '小食', calories_low: 80, calories_high: 150, base_price: 12, min_price: 9, max_price: 18, unit: '杯' },
]

const selectedCatalog = computed(() => catalog.value.find((c) => c.id === form.catalog_id) ?? null)

async function loadCatalog(): Promise<void> {
  catalogLoading.value = true
  catalogError.value = null
  try {
    const data = await getSkuCatalog()
    catalog.value = data.items
    catalogFallback.value = false
  } catch (err) {
    if (isNetworkError(err)) {
      catalog.value = FALLBACK_CATALOG
      catalogFallback.value = true
    } else {
      catalog.value = []
      catalogFallback.value = false
      catalogError.value = err instanceof Error ? err.message : '标准目录加载失败'
    }
  } finally {
    catalogLoading.value = false
  }
}

onMounted(loadCatalog)

function onCatalogChange(): void {
  lastError.value = null
  const c = selectedCatalog.value
  if (c) {
    form.price = c.base_price
  }
}

async function onSubmit(): Promise<void> {
  lastError.value = null
  if (!form.catalog_id) {
    ElMessage.warning('请选择标准目录')
    return
  }
  if (form.price <= 0) {
    ElMessage.warning('售价需大于 0')
    return
  }
  const c = selectedCatalog.value
  if (c && (form.price < c.min_price || form.price > c.max_price)) {
    ElMessage.warning(`售价需在目录限价区间 ¥${c.min_price} - ¥${c.max_price} 内`)
    return
  }
  submitting.value = true
  try {
    result.value = await upsertMerchantSku({
      merchant_id: form.merchant_id,
      catalog_id: form.catalog_id,
      price: form.price,
      stock: form.stock,
      status: form.status,
    })
    ElMessage.success('保存成功')
  } catch (err) {
    // 业务错误（如 2001 价格越出目录区间）把后端 message 原样展示
    lastError.value = err instanceof Error ? err.message : '提交失败'
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.retry-btn {
  margin-left: 8px;
}

.range-tip {
  font-size: 12px;
  color: #6b7280;
  line-height: 1.6;
}
</style>
