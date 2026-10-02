<template>
  <view class="sport-add">
    <!-- 未登录（§5.8 无权限态） -->
    <CNoPermission v-if="!userStore.isLogined" text="登录后添加运动" @action="goLogin" />

    <template v-else>
      <!-- 语音描述（G4）：说一句「今天爬楼20分钟」，自动回填运动名称 / 时长 -->
      <CCard title="语音描述" class="sport-add__card">
        <CButton block type="secondary" :loading="voice.transcribing.value" @click="onVoice">
          {{ voiceLabel }}
        </CButton>
        <text class="sport-add__hint">{{ voiceHint }}</text>
      </CCard>

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
import { computed, onUnmounted, reactive, ref } from 'vue'
import { useUserStore } from '@/stores/user'
import { redirectToLogin } from '@/utils/nav'
import { createSport } from '@/api/records'
import { useToast } from '@/composables/useToast'
import { useVoice } from '@/composables/useVoice'
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

/* ---------- 语音描述（G4） ---------- */

const voiceText = ref('')

/** 时长解析：阿拉伯数字 / 常见中文数字（含「半」），单位分/分钟/小时/时/min/h */
const DURATION_RE = /(\d+(?:\.\d+)?|[一二两三四五六七八九十半]+)\s*(?:个)?\s*(分钟|分|小时|时|min|h)/i

const CN_NUM: Record<string, number> = {
  一: 1,
  二: 2,
  两: 2,
  三: 3,
  四: 4,
  五: 5,
  六: 6,
  七: 7,
  八: 8,
  九: 9,
  十: 10,
  半: 0.5,
}

/** 中文数字（0.5/1~99）转阿拉伯数字，无法解析返回 NaN */
function cnToNum(s: string): number {
  if (s in CN_NUM) return CN_NUM[s]
  if (s.includes('十')) {
    const [a, b] = s.split('十')
    const tens = a ? (CN_NUM[a] ?? 0) : 1
    const ones = b ? (CN_NUM[b] ?? 0) : 0
    return tens * 10 + ones
  }
  return NaN
}

/** 从语音文本中提取时长（分钟），无有效值返回 null */
function parseDurationMin(text: string): number | null {
  const m = text.match(DURATION_RE)
  if (!m) return null
  const raw = /^\d/.test(m[1]) ? Number(m[1]) : cnToNum(m[1])
  if (!raw || Number.isNaN(raw)) return null
  const isHour = /小时|时|^h$/i.test(m[2])
  const minutes = Math.round(isHour ? raw * 60 : raw)
  if (minutes < 1 || minutes > DURATION_MAX) return null
  return minutes
}

/** 语音转写回填：命中标准项目则选名，未命中取去过量词的剩余文本；有则回填时长 */
function applyVoiceText(text: string) {
  const t = text.trim()
  voiceText.value = t
  const preset = presets.find((p) => t.includes(p.name))
  if (preset) {
    form.name = preset.name
  } else {
    const rest = t
      .replace(DURATION_RE, '')
      .replace(/[今天昨天今天下午上午晚上我了的。，,.！!？?]/g, '')
      .trim()
    form.name = rest || t
  }
  const minutes = parseDurationMin(t)
  if (minutes) form.duration = String(minutes)
  toast.success({ title: '已识别语音内容' })
}

const voice = useVoice({ onResult: applyVoiceText })

const voiceLabel = computed(() => {
  if (voice.transcribing.value) return '识别中…'
  return voice.recording.value ? '录音中…点击结束' : '按住说 / 点击开始语音描述'
})

const voiceHint = computed(() =>
  voiceText.value ? `已识别：${voiceText.value}，可修改下方信息` : '例如「快走30分钟」「今天爬楼20分钟」',
)

function onVoice() {
  voice.toggle()
}

onUnmounted(() => {
  voice.dispose()
})

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
  redirectToLogin()
}
</script>

<style lang="scss" scoped>
.sport-add {
  padding: $space-md;

  &__card {
    margin-bottom: $space-md;
  }

  &__hint {
    display: block;
    margin-top: $space-sm;
    font-size: $t-22;
    color: $text-3;
  }
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: $space-sm;
}
</style>