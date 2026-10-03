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

        <!-- 新增：先搜索食物；查不到时给 §2.4 出路（手动填热量 / 先跳过） -->
        <template v-if="panelMode === 'add' && !selectedFood">
          <CField label="搜索食物" required hint="食物库里查不到？下方可手动填热量新建">
            <CInput v-model="keyword" placeholder="如：清蒸鱼" @confirm="onSearch" />
          </CField>
          <CButton block :loading="searching" @click="onSearch">搜索</CButton>

          <!-- 搜到结果：沿用原选择列表 -->
          <view v-if="results.length" class="sheet__results">
            <view v-for="f in results" :key="f.id" class="sheet__result" @tap="selectFood(f)">
              <text class="sheet__result-name">{{ f.name }}</text>
              <text class="sheet__result-kcal">{{ Math.round(f.calories_100g) }} kcal/100g</text>
            </view>
          </view>

          <!-- 搜过但零结果：不再只有一句瞬时 toast，明确给「这是新菜？」出路（§2.4） -->
          <view v-else-if="noResult" class="sheet__fallback">
            <text class="sheet__fallback-title">没找到「{{ lastKeyword }}」，这是新菜？</text>
            <text class="sheet__fallback-text">
              手动填热量建个自定义食物（仅本人可见、待审核），或先跳过这条。
            </text>
            <view class="sheet__row">
              <CButton size="sm" @click="openCustom">手动填热量新建</CButton>
              <CButton size="sm" type="ghost" @click="closePanel">先跳过</CButton>
            </view>
          </view>

          <!-- 常驻入口：还没搜 / 搜过没结果都能直接手动新建 -->
          <CButton v-if="!customMode" type="ghost" block @click="openCustom">
            食物库查不到？手动填热量新建
          </CButton>

          <!--
            手动填热量 → 建自定义食物。与 pages/record/camera.vue 空态的自定义表单同口径，
            此处按任务约束内联最小实现（components/ 不在本轮可写范围），重复逻辑已登记汇报。
          -->
          <view v-if="customMode" class="sheet__custom">
            <CField label="食物名称" required :error="cName.trim() ? '' : '请填写名称'">
              <CInput v-model="cName" placeholder="如：自制牛油果沙拉" :maxlength="128" />
            </CField>
            <CField label="热量 (kcal/100g)" required :error="kcalError" hint="对齐后端：0 &lt; 热量 ≤ 1000">
              <CInput v-model="cCalories" type="digit" placeholder="如：88" />
            </CField>
            <view class="sheet__row">
              <CButton :loading="savingCustom" @click="onCreateCustom">建为自定义食物</CButton>
              <CButton type="ghost" @click="customMode = false">收起</CButton>
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
import { searchFood, createMeal, updateMeal, deleteMeal, listMeals, createCustomFood } from '@/api/records'
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

/** 自定义食物每 100g 热量上界（对齐后端 FoodCustomIn：0 < calories_100g ≤ 1000） */
const KCAL_MAX = 1000

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

// ---- 搜索零结果的出路（§2.4：手动填热量建自定义食物 / 先跳过）----
/** 上一次搜索的词与是否零结果（用于「没找到「X」，这是新菜？」文案） */
const noResult = ref(false)
const lastKeyword = ref('')
const customMode = ref(false)
const cName = ref('')
const cCalories = ref('')
const savingCustom = ref(false)

const kcalError = computed(() => {
  if (!customMode.value) return ''
  const kcal = Number(cCalories.value)
  if (!kcal || kcal <= 0) return '请填写热量'
  if (kcal > KCAL_MAX) return `热量需在 0~${KCAL_MAX} kcal/100g`
  return ''
})

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
  noResult.value = false
  lastKeyword.value = ''
  resetCustom()
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
    lastKeyword.value = kw
    noResult.value = !res.items.length
    if (noResult.value) {
      // 出路在弹层里常驻展示（下方「这是新菜？」块），toast 只做一次性提醒
      if (!cName.value.trim()) cName.value = kw
      toast.info({ title: '没找到，可换个关键词，或手动填热量新建' })
    }
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

function resetCustom() {
  customMode.value = false
  cName.value = ''
  cCalories.value = ''
}

/** 展开手动新建表单；名称预填当前/上次搜索词，减少一次输入 */
function openCustom() {
  customMode.value = true
  if (!cName.value.trim()) cName.value = lastKeyword.value || keyword.value.trim()
}

/**
 * 建自定义食物（仅本人可见、待审核），建好即作为「已选食物」进入既有的餐次/分量表单，
 * 复用同一条 createMeal 入账链路——不为「搜不到」另开第二条写账路径。
 */
async function onCreateCustom() {
  const name = cName.value.trim()
  const kcal = Number(cCalories.value)
  if (!name) {
    toast.error({ title: '请填写食物名称' })
    return
  }
  if (!kcal || kcal <= 0 || kcal > KCAL_MAX) {
    toast.error({ title: `热量需在 0~${KCAL_MAX} kcal/100g` })
    return
  }
  savingCustom.value = true
  try {
    const food = await createCustomFood({ name, calories_100g: kcal })
    selectedFood.value = { id: food.id, name: food.name, calories_100g: food.calories_100g }
    customMode.value = false
    noResult.value = false
    results.value = []
    formAmount.value = '100'
    toast.success({ title: '已新建自定义食物，待审核' })
  } catch (e) {
    // 错误信息已由 request 封装 toast
  } finally {
    savingCustom.value = false
  }
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
  noResult.value = false
  lastKeyword.value = ''
  resetCustom()
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

  // 搜索零结果的出路块（§2.4「这是新菜？手动填热量或先跳过」）
  &__fallback {
    margin-top: $space-md;
    padding: $space-sm $space-md;
    background: rgba($warn, 0.1);
    border-radius: $radius-sm;
  }

  &__fallback-title {
    display: block;
    font-size: $t-26;
    font-weight: 500;
    color: $text-1;
  }

  &__fallback-text {
    display: block;
    margin-top: 2rpx;
    font-size: $t-22;
    color: $text-2;
  }

  &__custom {
    margin-top: $space-md;
    padding-top: $space-md;

    @include hairline(top);
  }

  &__row {
    display: flex;
    flex-wrap: wrap;
    gap: $space-sm;
    margin-top: $space-sm;
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