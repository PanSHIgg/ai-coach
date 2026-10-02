<template>
  <view class="food">
    <!-- 未登录（§5.8 无权限态） -->
    <CNoPermission v-if="!userStore.isLogined" text="登录后查看饮食记录" @action="goLogin" />

    <template v-else>
      <!-- 日期 + 合计 -->
      <CCard class="food__head">
        <view class="food__head-row">
          <picker mode="date" :value="date" @change="onDateChange">
            <view class="food__date">{{ dateText }} ▾</view>
          </picker>
          <text class="food__total">合计 {{ totalKcal }} kcal</text>
        </view>
      </CCard>

      <!-- 加载骨架 / 错误重试 / 内容 -->
      <CSkeleton v-if="loading" type="card" class="food__card" />
      <CError v-else-if="loadError" @retry="reload" />

      <template v-else>
        <CCard v-if="!meals.length" class="food__card">
          <CEmpty text="这一天还没有饮食记录" @action="openAdd" />
        </CCard>

        <CCard v-for="g in groups" :key="g.value" :title="g.label" class="food__card">
          <template #extra>
            <text class="food__g-kcal">{{ g.kcal }} kcal</text>
          </template>
          <view v-for="m in g.items" :key="m.id" class="food__item">
            <view class="food__item-main" @tap="openEdit(m)">
              <text class="food__item-name">{{ m.food_name }}</text>
              <text class="food__item-sub">
                {{ amountText(m.amount_g) }} · {{ Math.round(m.calories) }} kcal
              </text>
            </view>
            <view class="food__item-actions">
              <text class="food__link" @tap="openEdit(m)">编辑</text>
              <text class="food__link food__link--danger" @tap="onDelete(m)">删除</text>
            </view>
          </view>
        </CCard>
      </template>

      <view class="food__bar">
        <CButton block @click="openAdd">新增记录</CButton>
      </view>
    </template>

    <!-- 新增 / 编辑底部弹层 -->
    <view v-if="panelOpen" class="sheet">
      <view class="sheet__mask" @tap="closePanel" />
      <view class="sheet__body">
        <view class="sheet__head">
          <text class="sheet__title">{{ panelMode === 'edit' ? '编辑记录' : '新增记录' }}</text>
          <text class="sheet__close" @tap="closePanel">✕</text>
        </view>

        <!-- 新增：先搜索食物 -->
        <template v-if="panelMode === 'add' && !selectedFood">
          <CField label="搜索食物" required>
            <CInput v-model="keyword" placeholder="如：清蒸鱼" @confirm="onSearch" />
          </CField>
          <CButton block :loading="searching" @click="onSearch">搜索</CButton>
          <view v-if="results.length" class="sheet__results">
            <view v-for="f in results" :key="f.id" class="sheet__result" @tap="selectFood(f)">
              <text class="sheet__result-name">{{ f.name }}</text>
              <text class="sheet__result-kcal">{{ Math.round(f.calories_100g) }} kcal/100g</text>
            </view>
          </view>
        </template>

        <!-- 表单：餐次 + 分量 -->
        <template v-else>
          <view v-if="panelMode === 'edit' && editing" class="sheet__food">
            <text class="sheet__food-name">{{ editing.food_name }}</text>
          </view>
          <view v-else-if="selectedFood" class="sheet__food">
            <text class="sheet__food-name">{{ selectedFood.name }}</text>
            <text class="sheet__food-sub">{{ Math.round(selectedFood.calories_100g) }} kcal/100g</text>
          </view>

          <CField label="餐次" required>
            <view class="seg">
              <CButton
                v-for="t in MEAL_TYPES"
                :key="t.value"
                size="sm"
                :type="formMealType === t.value ? 'primary' : 'secondary'"
                @click="formMealType = t.value"
              >
                {{ t.label }}
              </CButton>
            </view>
          </CField>

          <CField label="分量" required hint="单位 g">
            <CInput v-model="formAmount" type="digit" placeholder="如 150" />
          </CField>

          <CButton block :loading="saving" @click="onSubmit">
            {{ panelMode === 'edit' ? '保存' : '确认添加' }}
          </CButton>
        </template>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { useUserStore } from '@/stores/user'
import { redirectToLogin } from '@/utils/nav'
import { searchFood, createMeal, updateMeal, deleteMeal, listMeals } from '@/api/records'
import { useToast } from '@/composables/useToast'
import type { FoodItem, MealRecordOut } from '@/types/api'

const MEAL_TYPES = [
  { value: 1, label: '早餐' },
  { value: 2, label: '午餐' },
  { value: 3, label: '晚餐' },
  { value: 4, label: '加餐' },
] as const

/** 分量上界（对齐后端 MealCreateIn/MealUpdateIn：amount_g > 0 且 ≤ 10000） */
const AMOUNT_MAX = 10000

const userStore = useUserStore()
const toast = useToast()

function fmtDate(d = new Date()): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const date = ref(fmtDate())
const dateText = computed(() => {
  const [, m, d] = date.value.split('-')
  return `${Number(m)}月${Number(d)}日`
})

const loading = ref(false)
const loadError = ref(false)
const meals = ref<MealRecordOut[]>([])

// 按餐次分组（仅展示有记录的餐次）
const groups = computed(() =>
  MEAL_TYPES.map((t) => {
    const list = meals.value.filter((m) => m.meal_type === t.value)
    const kcal = Math.round(list.reduce((sum, m) => sum + m.calories, 0))
    return { value: t.value, label: t.label, kcal, items: list }
  }).filter((g) => g.items.length),
)
const totalKcal = computed(() => Math.round(meals.value.reduce((sum, m) => sum + m.calories, 0)))

// ---- 弹层状态 ----
const panelOpen = ref(false)
const panelMode = ref<'add' | 'edit' | null>(null)
const keyword = ref('')
const searching = ref(false)
const results = ref<FoodItem[]>([])
const selectedFood = ref<FoodItem | null>(null)
const editing = ref<MealRecordOut | null>(null)
const formMealType = ref<1 | 2 | 3 | 4>(1)
const formAmount = ref('')
const saving = ref(false)

onShow(() => {
  if (userStore.isLogined) reload()
})

async function reload() {
  loading.value = true
  loadError.value = false
  try {
    const res = await listMeals({ date: date.value, page_size: 100 })
    meals.value = res.items
  } catch (e) {
    loadError.value = true
  } finally {
    loading.value = false
  }
}

function onDateChange(e: { detail: { value: string } }) {
  date.value = e.detail.value
  reload()
}

/** 重量展示：<1000g 显示 g，≥1000g 换算 kg（§13.1） */
function amountText(g: number): string {
  return g >= 1000 ? `${(g / 1000).toFixed(2)}kg` : `${Number(g)}g`
}

// ---- 新增 ----
function openAdd() {
  panelMode.value = 'add'
  keyword.value = ''
  results.value = []
  selectedFood.value = null
  formMealType.value = 1
  formAmount.value = '100'
  panelOpen.value = true
}

async function onSearch() {
  const kw = keyword.value.trim()
  if (!kw) {
    toast.error({ title: '请输入食物名称' })
    return
  }
  searching.value = true
  try {
    const res = await searchFood({ keyword: kw, limit: 20 })
    results.value = res.items
    if (!res.items.length) toast.info({ title: '没找到，试试其他关键词' })
  } catch (e) {
    // 错误信息已由 request 封装 toast
  } finally {
    searching.value = false
  }
}

function selectFood(f: FoodItem) {
  selectedFood.value = f
  formAmount.value = '100'
}

// ---- 编辑 ----
function openEdit(m: MealRecordOut) {
  panelMode.value = 'edit'
  editing.value = m
  selectedFood.value = null
  formMealType.value = m.meal_type
  formAmount.value = String(m.amount_g)
  panelOpen.value = true
}

function closePanel() {
  panelOpen.value = false
  panelMode.value = null
  selectedFood.value = null
  editing.value = null
  results.value = []
}

async function onSubmit() {
  const amount = Number(formAmount.value)
  if (!amount || amount <= 0) {
    toast.error({ title: '请填写正确的分量' })
    return
  }
  if (amount > AMOUNT_MAX) {
    toast.error({ title: `分量需在 0~${AMOUNT_MAX}g` })
    return
  }
  saving.value = true
  try {
    if (panelMode.value === 'add') {
      if (!selectedFood.value) return
      await createMeal({
        meal_type: formMealType.value,
        food_id: selectedFood.value.id,
        amount_g: amount,
        source: 3, // 手动录入
      })
      toast.success({ title: '已添加' })
    } else if (editing.value) {
      await updateMeal(editing.value.id, {
        meal_type: formMealType.value,
        amount_g: amount,
      })
      toast.success({ title: '已保存' })
    }
    closePanel()
    await reload()
  } catch (e) {
    // 错误信息已由 request 封装 toast
  } finally {
    saving.value = false
  }
}

// ---- 删除（二次确认，§13.2）----
function onDelete(m: MealRecordOut) {
  uni.showModal({
    title: '确认删除',
    content: `删除「${m.food_name}」这条记录？`,
    success: async (r) => {
      if (!r.confirm) return
      try {
        await deleteMeal(m.id)
        toast.success({ title: '已删除' })
        await reload()
      } catch (e) {
        // 错误信息已由 request 封装 toast
      }
    },
  })
}

function goLogin() {
  redirectToLogin()
}
</script>

<style lang="scss" scoped>
.food {
  padding: $space-md;

  &__head {
    margin-bottom: $space-md;
  }

  &__head-row {
    @include flex-between;
  }

  &__date {
    font-size: $t-28;
    font-weight: 500;
    color: $text-1;
  }

  &__total {
    font-size: $t-26;
    color: $brand;
  }

  &__card {
    margin-bottom: $space-md;
  }

  &__g-kcal {
    font-size: $t-22;
    color: $text-2;
  }

  &__item {
    @include flex-between;

    padding: $space-sm 0;

    &:not(:last-child) {
      @include hairline(bottom);
    }
  }

  &__item-main {
    flex: 1;
    min-width: 0;
  }

  &__item-name {
    display: block;
    font-size: $t-26;
    color: $text-1;
  }

  &__item-sub {
    font-size: $t-22;
    color: $text-2;
  }

  &__item-actions {
    display: flex;
    gap: $space-md;
    flex-shrink: 0;
  }

  &__link {
    font-size: $t-24;
    color: $brand;

    &--danger {
      color: $danger;
    }
  }

  &__bar {
    margin-top: $space-md;
    margin-bottom: $space-xl;
  }
}

.sheet {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  left: 0;
  z-index: $z-popup;

  &__mask {
    position: absolute;
    top: 0;
    right: 0;
    bottom: 0;
    left: 0;
    background: $mask;
  }

  &__body {
    position: absolute;
    right: 0;
    bottom: 0;
    left: 0;
    max-height: 80vh;
    overflow-y: auto;
    padding: $space-lg;
    padding-bottom: calc(#{$space-lg} + env(safe-area-inset-bottom));
    background: $card;
    border-radius: $radius-lg $radius-lg 0 0;
    box-shadow: $shadow-lg;
  }

  &__head {
    @include flex-between;

    margin-bottom: $space-md;
  }

  &__title {
    font-size: $t-28;
    font-weight: 500;
    color: $text-1;
  }

  &__close {
    font-size: $t-28;
    color: $text-3;
  }

  &__results {
    margin-top: $space-md;
  }

  &__result {
    @include flex-between;

    padding: $space-sm 0;

    &:not(:last-child) {
      @include hairline(bottom);
    }
  }

  &__result-name {
    font-size: $t-26;
    color: $text-1;
  }

  &__result-kcal {
    font-size: $t-22;
    color: $text-2;
  }

  &__food {
    margin-bottom: $space-md;
  }

  &__food-name {
    display: block;
    font-size: $t-28;
    font-weight: 500;
    color: $text-1;
  }

  &__food-sub {
    font-size: $t-22;
    color: $text-2;
  }
}

.seg {
  display: flex;
  flex-wrap: wrap;
  gap: $space-sm;
}
</style>