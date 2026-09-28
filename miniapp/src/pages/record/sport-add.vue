<template>
  <view class="sport-add">
    <!-- 未登录（§5.8 无权限态） -->
    <CNoPermission v-if="!userStore.isLogined" text="登录后添加运动" @action="goLogin" />

    <template v-else>
      <!-- 标准运动项目快捷选择（选中自动带出 MET） -->
      <CCard title="标准运动项目" class="sport-add__card">
        <view class="chips">
          <CButton
            v-for="p in presets"
            :key="p.name"
            size="sm"
            :type="form.name === p.name ? 'primary' : 'secondary'"
            @click="pickPreset(p)"
          >
            {{ p.name }}
          </CButton>
        </view>
      </CCard>

      <!-- 手动填写 -->
      <CCard title="运动详情" class="sport-add__card">
        <CField label="运动名称" required>
          <CInput v-model="form.name" placeholder="如：爬楼" />
        </CField>
        <CField label="时长" required hint="单位 分钟">
          <CInput v-model="form.duration" type="number" placeholder="如 30" />
        </CField>
        <CField label="MET" hint="由后端按运动名称统一映射，无需填写">
          <text class="sport-add__met">{{ estimatedMet.toFixed(1) }}（预估值）</text>
        </CField>
      </CCard>

      <!-- 提交中按钮置灰（§13.2） -->
      <CButton block :loading="saving" @click="onSubmit">保存</CButton>
    </template>
  </view>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useUserStore } from '@/stores/user'
import { createSport } from '@/api/records'
import { useToast } from '@/composables/useToast'
import type { SportIn } from '@/types/api'

const userStore = useUserStore()
const toast = useToast()

/** 时长上界（对齐后端 SportIn：duration_min ≥ 1 且 ≤ 1440，即 24h） */
const DURATION_MAX = 1440

/** MET 名称映射（与后端 record_service.SPORT_MET 口径一致，仅用于前端预估展示） */
const MET_BY_NAME: Record<string, number> = {
  慢跑: 8.0,
  快走: 4.3,
  散步: 2.5,
  跳绳: 10.0,
  骑行: 6.0,
  游泳: 6.0,
  羽毛球: 5.5,
  瑜伽: 2.5,
  爬楼: 4.0,
  爬楼梯: 4.0,
}
/** 名字未命中时后端默认中等强度值 */
const DEFAULT_SPORT_MET = 6.0

// 标准运动项目（名称；MET 仅用于展示预估，实际以后端映射为准）
const presets = [
  { name: '慢跑' },
  { name: '快走' },
  { name: '散步' },
  { name: '跳绳' },
  { name: '骑行' },
  { name: '游泳' },
  { name: '羽毛球' },
  { name: '瑜伽' },
  { name: '爬楼' },
]

const form = reactive({
  name: '',
  duration: '',
})
const saving = ref(false)

/** 预估 MET（仅展示，最终由后端按 sport_name 统一映射） */
const estimatedMet = computed(() => MET_BY_NAME[form.name.trim()] ?? DEFAULT_SPORT_MET)

function pickPreset(p: { name: string }) {
  form.name = p.name
}

async function onSubmit() {
  if (!form.name.trim()) {
    toast.error({ title: '请填写运动名称' })
    return
  }
  const duration = Number(form.duration)
  if (!duration || duration <= 0) {
    toast.error({ title: '请填写正确的时长' })
    return
  }
  if (duration > DURATION_MAX) {
    toast.error({ title: `时长需在 1~${DURATION_MAX} 分钟` })
    return
  }
  saving.value = true
  try {
    // 不传 met：由后端按 sport_name 统一映射，消除前后端双口径
    const payload: SportIn = {
      sport_name: form.name.trim(),
      duration_min: Math.round(duration),
    }
    await createSport(payload)
    toast.success({ title: '已添加' })
    setTimeout(() => uni.navigateBack(), 600)
  } catch (e) {
    // 错误信息已由 request 封装 toast
  } finally {
    saving.value = false
  }
}

function goLogin() {
  uni.navigateTo({ url: '/pages/login/login' })
}
</script>

<style lang="scss" scoped>
.sport-add {
  padding: $space-md;

  &__card {
    margin-bottom: $space-md;
  }
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: $space-sm;
}
</style>