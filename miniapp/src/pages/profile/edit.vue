<template>
  <view class="page-shell">
    <CCard title="身体档案" class="edit__card">
      <CSkeleton v-if="loading" type="card" />
      <view v-else class="edit__form">
        <!-- 性别（分段控件：CButton 组） -->
        <CField label="性别" required>
          <view class="seg">
            <CButton
              v-for="opt in genderOptions"
              :key="opt.value"
              size="sm"
              :type="form.gender === opt.value ? 'primary' : 'secondary'"
              @click="form.gender = opt.value"
            >
              {{ opt.label }}
            </CButton>
          </view>
        </CField>

        <!-- 身高 -->
        <CField label="身高" required hint="单位 cm" :error="errors.height_cm">
          <CInput v-model="form.height_cm" type="digit" placeholder="如 175" />
        </CField>

        <!-- 当前体重 -->
        <CField label="当前体重" required hint="单位 kg" :error="errors.current_weight">
          <CInput v-model="form.current_weight" type="digit" placeholder="如 75.5" />
        </CField>

        <!-- 目标体重 -->
        <CField label="目标体重" hint="单位 kg，选填" :error="errors.target_weight">
          <CInput v-model="form.target_weight" type="digit" placeholder="如 70" />
        </CField>

        <!-- 出生年份 -->
        <CField label="出生年份" hint="用于 BMR 计算" :error="errors.birth_year">
          <CInput v-model="form.birth_year" type="number" placeholder="如 1995" />
        </CField>

        <!-- 目标类型（分段控件） -->
        <CField label="目标类型" required>
          <view class="seg">
            <CButton
              v-for="opt in targetTypeOptions"
              :key="opt.value"
              size="sm"
              :type="form.target_type === opt.value ? 'primary' : 'secondary'"
              @click="form.target_type = opt.value"
            >
              {{ opt.label }}
            </CButton>
          </view>
        </CField>

        <!-- 活动水平（分段控件） -->
        <CField label="活动水平" required hint="PAL 系数：卧床 1.2 / 久坐 1.4 / 轻度 1.6 / 中度 1.8 / 高度 2.0">
          <view class="seg seg--wrap">
            <CButton
              v-for="opt in activityOptions"
              :key="opt.value"
              size="sm"
              :type="form.activity_level === opt.value ? 'primary' : 'secondary'"
              @click="form.activity_level = opt.value"
            >
              {{ opt.label }}
            </CButton>
          </view>
        </CField>

        <!-- 每周目标节奏（分段控件，选填） -->
        <CField label="每周目标" hint="kg/周，选填">
          <view class="seg seg--wrap">
            <CButton
              v-for="opt in paceOptions"
              :key="opt.value"
              size="sm"
              :type="form.goal_pace === opt.value ? 'primary' : 'secondary'"
              @click="form.goal_pace = opt.value"
            >
              {{ opt.label }}
            </CButton>
          </view>
        </CField>
      </view>
    </CCard>

    <CButton class="edit__submit" block :loading="saving" :disabled="saving" @click="onSave">
      {{ saving ? '保存中…' : '保存' }}
    </CButton>
  </view>
</template>

<script setup lang="ts">
import { reactive, ref, onMounted } from 'vue'
import type { BodyProfileIn, BodyProfileOut } from '@/types/api'
import { getBodyProfile, saveBodyProfile } from '@/api/profile'
import { useUserStore } from '@/stores/user'
import { useToast } from '@/composables/useToast'

const userStore = useUserStore()
const toast = useToast()
const loading = ref(true)
const saving = ref(false)

const genderOptions = [
  { label: '男', value: 1 as const },
  { label: '女', value: 2 as const },
]
const targetTypeOptions = [
  { label: '减脂', value: 1 as const },
  { label: '增肌', value: 2 as const },
  { label: '维持', value: 3 as const },
]
// 活动水平 5 档，文案对齐契约 openapi ActivityLevel（1卧床 2久坐 3轻度 4中度 5高度）
const activityOptions = [
  { label: '卧床', value: 1 as const },
  { label: '久坐', value: 2 as const },
  { label: '轻度', value: 3 as const },
  { label: '中度', value: 4 as const },
  { label: '高度', value: 5 as const },
]
// 每周目标 kg 档位（契约 goal_pace 为整数档：0=0.25kg 1=0.5kg 2=0.75kg 3=1.0kg，缺省 1）
const paceOptions = [
  { label: '0.25', value: 0 },
  { label: '0.5', value: 1 },
  { label: '0.75', value: 2 },
  { label: '1.0', value: 3 },
]

// 输入框走字符串，保存时统一转数字
const form = reactive({
  gender: 1 as 1 | 2,
  height_cm: '',
  current_weight: '',
  target_weight: '',
  birth_year: '',
  target_type: 1 as 1 | 2 | 3,
  activity_level: 2 as 1 | 2 | 3 | 4 | 5,
  goal_pace: null as number | null,
})

// 字段级校验错误（红字，CField error 优先于 hint）
const errors = reactive({
  height_cm: '',
  current_weight: '',
  target_weight: '',
  birth_year: '',
})

// 【假设】边界对齐 QA 用例（身高 0/200、体重 0/500、年龄负数）；
// 后端 schema（profile.py）已约束数值范围：height_cm gt=0,le=200、current_weight gt=0,le=500，
// 前端先行拦截 + 后端兜底
const HEIGHT_MAX = 200 // cm
const WEIGHT_MAX = 500 // kg

onMounted(async () => {
  try {
    const p = await getBodyProfile()
    if (p) prefill(p)
  } catch (e) {
    // 首次建档无数据 / 网络异常：保持默认值（错误已由 request toast）
  } finally {
    loading.value = false
  }
})

function prefill(p: BodyProfileOut) {
  form.gender = p.gender
  form.height_cm = String(p.height_cm)
  form.current_weight = String(p.current_weight)
  form.target_weight = p.target_weight != null ? String(p.target_weight) : ''
  form.birth_year = p.birth_year != null ? String(p.birth_year) : ''
  form.target_type = p.target_type
  form.activity_level = p.activity_level
  form.goal_pace = p.goal_pace ?? null
}

/** 校验：必填 + 数值边界，返回是否通过 */
function validate(): boolean {
  errors.height_cm = ''
  errors.current_weight = ''
  errors.target_weight = ''
  errors.birth_year = ''

  const height = Number(form.height_cm)
  if (!form.height_cm) errors.height_cm = '请填写身高'
  else if (!Number.isFinite(height) || height <= 0 || height > HEIGHT_MAX)
    errors.height_cm = `身高需在 0~${HEIGHT_MAX}cm`

  const weight = Number(form.current_weight)
  if (!form.current_weight) errors.current_weight = '请填写当前体重'
  else if (!Number.isFinite(weight) || weight <= 0 || weight > WEIGHT_MAX)
    errors.current_weight = `请输入 1-${WEIGHT_MAX} 之间的体重（kg）`

  if (form.target_weight) {
    const tw = Number(form.target_weight)
    if (!Number.isFinite(tw) || tw <= 0 || tw > WEIGHT_MAX)
      errors.target_weight = `请输入 1-${WEIGHT_MAX} 之间的目标体重（kg）`
  }

  if (form.birth_year) {
    const year = Number(form.birth_year)
    const nowYear = new Date().getFullYear()
    const yearMin = nowYear - 120
    const yearMax = nowYear - 10
    if (!Number.isInteger(year) || year < yearMin || year > yearMax)
      errors.birth_year = `请输入 ${yearMin}-${yearMax} 之间的出生年份`
  }

  return !errors.height_cm && !errors.current_weight && !errors.target_weight && !errors.birth_year
}

async function onSave() {
  if (saving.value) return // 防重复提交
  if (!validate()) {
    toast.error({ title: '请检查表单填写' })
    return
  }
  saving.value = true
  try {
    const payload: BodyProfileIn = {
      gender: form.gender,
      height_cm: Number(form.height_cm),
      current_weight: Number(form.current_weight),
      target_weight: form.target_weight ? Number(form.target_weight) : null,
      birth_year: form.birth_year ? Number(form.birth_year) : null,
      target_type: form.target_type,
      activity_level: form.activity_level,
      goal_pace: form.goal_pace,
    }
    const saved = await saveBodyProfile(payload)
    // 回填 store：首页核心指标 / 建档引导即时更新
    userStore.setProfile(saved)
    toast.success({ title: '保存成功' })
    // 登录后直接进建档页（reLaunch 无返回栈）→ 回首页；否则返回上一页
    const pages = getCurrentPages()
    setTimeout(() => {
      if (pages.length > 1) uni.navigateBack()
      else uni.reLaunch({ url: '/pages/index' })
    }, 600)
  } catch (e) {
    // 错误信息已由 request 封装 toast
  } finally {
    saving.value = false
  }
}
</script>

<style lang="scss" scoped>
.page-shell {
  padding: $space-md;
}

.edit {
  &__card {
    margin-bottom: $space-md;
  }

  &__form {
    :deep(.c-field) {
      margin-bottom: $space-md;
    }
  }

  &__submit {
    margin-bottom: $space-xl;
  }
}

.seg {
  display: flex;
  gap: $space-sm;

  &--wrap {
    flex-wrap: wrap;
  }
}
</style>