<template>
  <view class="camera">
    <!-- 未登录（§5.8 无权限态） -->
    <CNoPermission v-if="!userStore.isLogined" text="登录后使用拍照记录" @action="goLogin" />

    <template v-else>
      <CCard title="拍照识别" class="camera__card">
        <!-- 1. 未选图：引导拍照 / 选择 -->
        <view v-if="!imagePath" class="camera__empty">
          <view class="camera__empty-icon">📷</view>
          <text class="camera__empty-text">拍下这一餐，AI 帮你识别热量</text>
          <CButton block @click="choosePic">选择 / 拍摄照片</CButton>
          <CButton class="camera__manual" type="ghost" block @click="goManual">手动搜索录入</CButton>
        </view>

        <template v-else>
          <!-- 图片预览 -->
          <image class="camera__preview" :src="imagePath" mode="aspectFill" />

          <!-- 2. 识别中：骨架 -->
          <CSkeleton v-if="recognizing" type="card" class="camera__skeleton" />

          <!-- 3. 识别失败 / 模糊：给出换个角度或手动搜索兜底 -->
          <view v-else-if="failed" class="camera__fail">
            <CError text="没识别出来，换个角度再试试" @retry="choosePic" />
            <CButton class="camera__manual" type="secondary" block @click="goManual">
              手动搜索录入
            </CButton>
          </view>

          <!-- 4. 识别结果：置信度 <0.7 标红需确认，可修正分量 -->
          <view v-else-if="items.length" class="camera__result">
            <text v-if="needConfirm" class="camera__tip">部分结果置信度较低，请确认分量后再记录</text>

            <view v-for="(it, i) in items" :key="i" class="item">
              <view class="item__head">
                <text class="item__name">{{ it.name }}</text>
                <text class="item__badge" :class="isLow(it) ? 'item__badge--low' : 'item__badge--ok'">
                  {{ confidenceText(it) }}{{ isLow(it) ? ' 需确认' : '' }}
                </text>
              </view>
              <view class="item__body">
                <text class="item__kcal">{{ itemCalories(it) }} kcal</text>
                <view class="item__amount">
                  <CInput v-model="it.amountText" type="digit" placeholder="分量" />
                  <text class="item__unit">g</text>
                </view>
              </view>
            </view>

            <!-- 餐次选择（createMeal 必填） -->
            <CField label="记到哪一餐" required>
              <view class="seg">
                <CButton
                  v-for="t in MEAL_TYPES"
                  :key="t.value"
                  size="sm"
                  :type="mealType === t.value ? 'primary' : 'secondary'"
                  @click="mealType = t.value"
                >
                  {{ t.label }}
                </CButton>
              </view>
            </CField>

            <CButton block :loading="saving" @click="onSave">记下来</CButton>
            <CButton class="camera__manual" type="ghost" block @click="choosePic">换张照片</CButton>
          </view>
        </template>
      </CCard>
    </template>
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useUserStore } from '@/stores/user'
import { createMeal } from '@/api/records'
import { BASE_URL, getToken } from '@/api/request'
import { useToast } from '@/composables/useToast'
import type { Envelope, RecognizeData, RecognizedItem } from '@/types/api'

/** 识别项 + 可编辑分量（字符串便于输入框双向绑定） */
interface EditableItem extends RecognizedItem {
  amountText: string
}

const MEAL_TYPES = [
  { value: 1, label: '早餐' },
  { value: 2, label: '午餐' },
  { value: 3, label: '晚餐' },
  { value: 4, label: '加餐' },
] as const

/** 置信度阈值：<0.7 需用户确认（§5.7 / §13.3） */
const LOW_CONFIDENCE = 0.7

/** 分量上界（对齐后端 MealCreateIn：amount_g > 0 且 ≤ 10000） */
const AMOUNT_MAX = 10000

const userStore = useUserStore()
const toast = useToast()

const imagePath = ref('')
const recognizing = ref(false)
const failed = ref(false)
const needConfirm = ref(false)
const items = ref<EditableItem[]>([])
const saving = ref(false)

// 默认餐次按当前时段推断
const hour = new Date().getHours()
const mealType = ref<1 | 2 | 3 | 4>(hour < 10 ? 1 : hour < 15 ? 2 : hour < 20 ? 3 : 4)

/** 选择 / 拍摄图片（uni.chooseImage，相机 + 相册） */
function choosePic() {
  uni.chooseImage({
    count: 1,
    sizeType: ['compressed'],
    sourceType: ['camera', 'album'],
    success: (res) => {
      const path = (res.tempFilePaths as string[])[0]
      if (!path) return
      imagePath.value = path
      recognize(path)
    },
  })
}

/**
 * 上传图片调用识别接口（multipart/form-data，字段名 image，见 openapi /api/meal/recognize）。
 * 【假设】request.ts 仅封装 JSON 请求，multipart 需走 uni.uploadFile，故此处内联实现，
 * 仅复用 BASE_URL / getToken；首期后端为 stub，按契约解析 items + need_confirm。
 */
function uploadRecognize(filePath: string): Promise<RecognizeData> {
  const token = getToken()
  return new Promise((resolve, reject) => {
    uni.uploadFile({
      url: `${BASE_URL}/api/meal/recognize`,
      filePath,
      name: 'image',
      header: token ? { Authorization: `Bearer ${token}` } : {},
      success: (res) => {
        let env: Envelope<RecognizeData> | null = null
        try {
          env = JSON.parse(res.data) as Envelope<RecognizeData>
        } catch (e) {
          env = null
        }
        if (res.statusCode >= 200 && res.statusCode < 300 && env && env.code === 0 && env.data) {
          resolve(env.data)
        } else {
          reject(new Error((env && env.message) || '识别失败'))
        }
      },
      fail: (err) => reject(new Error(err.errMsg || '图片上传失败')),
    })
  })
}

async function recognize(path: string) {
  recognizing.value = true
  failed.value = false
  items.value = []
  try {
    const data = await uploadRecognize(path)
    items.value = (data.items || []).map((it) => ({ ...it, amountText: String(it.amount_g) }))
    needConfirm.value = data.need_confirm
    if (!items.value.length) failed.value = true
  } catch (e) {
    failed.value = true
    toast.error({ title: (e as Error).message || '识别失败，换个角度或手动搜索' })
  } finally {
    recognizing.value = false
  }
}

function isLow(it: EditableItem): boolean {
  return (it.confidence ?? 0) < LOW_CONFIDENCE
}
function confidenceText(it: EditableItem): string {
  return `${Math.round((it.confidence ?? 0) * 100)}%`
}
/** 分量修正后按比例估算热量（后端 createMeal 会按 food_id + amount_g 重算） */
function itemCalories(it: EditableItem): number {
  const g = Number(it.amountText)
  if (!g || !it.amount_g) return Math.round(it.calories)
  return Math.round((it.calories * g) / it.amount_g)
}

/** 写入饮食记录（source=1 拍照） */
async function onSave() {
  if (!items.value.length) return
  // food_id 为 null = 未命中食物库（契约 nullable）；MealCreateIn.food_id 必填，故只能跳过
  const matched = items.value.filter((it) => it.food_id != null)
  if (matched.length < items.value.length) {
    toast.error({ title: '未匹配到食物，请手动搜索录入' })
    if (!matched.length) {
      goManual()
      return
    }
  }
  for (const it of matched) {
    const g = Number(it.amountText)
    if (!g || g <= 0) {
      toast.error({ title: '请填写正确的分量' })
      return
    }
    if (g > AMOUNT_MAX) {
      toast.error({ title: `分量需在 0~${AMOUNT_MAX}g` })
      return
    }
  }
  saving.value = true
  try {
    for (const it of matched) {
      await createMeal({
        meal_type: mealType.value,
        food_id: it.food_id as number,
        amount_g: Number(it.amountText),
        source: 1,
        // 【假设】本地临时路径非服务端 URL，首期 image_url 留空
        image_url: null,
      })
    }
    toast.success({ title: '已记下来' })
    // 广播识别结果：吃什么页 uni.$on('eat:recognized') 接收（见 pages/eat/eat.vue）
    uni.$emit('eat:recognized', { foods: items.value.map((i) => i.name) })
    setTimeout(() => uni.navigateBack(), 600)
  } catch (e) {
    // 错误信息已由 request 封装 toast
  } finally {
    saving.value = false
  }
}

function goManual() {
  uni.redirectTo({ url: '/pages/record/food-list' })
}
function goLogin() {
  uni.navigateTo({ url: '/pages/login/login' })
}
</script>

<style lang="scss" scoped>
.camera {
  padding: $space-md;

  &__card {
    margin-bottom: $space-md;
  }

  &__empty {
    @include flex-center(column);

    padding: $space-lg 0;
  }

  &__empty-icon {
    @include flex-center;

    width: 120rpx;
    height: 120rpx;
    margin-bottom: $space-md;
    font-size: 64rpx;
    background: #f3f4f6;
    border-radius: 50%;
  }

  &__empty-text {
    margin-bottom: $space-lg;
    font-size: $t-26;
    color: $text-2;
  }

  &__preview {
    width: 100%;
    height: 360rpx;
    margin-bottom: $space-md;
    border-radius: $radius;
    background: $bg;
  }

  &__skeleton {
    margin-bottom: $space-md;
  }

  &__tip {
    display: block;
    margin-bottom: $space-md;
    padding: $space-sm $space-md;
    font-size: $t-22;
    color: $warn;
    background: rgba(245, 158, 11, 0.1);
    border-radius: $radius-sm;
  }

  &__manual {
    margin-top: $space-sm;
  }
}

.item {
  padding: $space-sm 0;

  &:not(:last-child) {
    @include hairline(bottom);
  }

  &__head {
    @include flex-between;

    margin-bottom: $space-xs;
  }

  &__name {
    font-size: $t-26;
    font-weight: 500;
    color: $text-1;
  }

  &__badge {
    font-size: $t-22;

    &--ok {
      color: $success;
    }

    &--low {
      color: $warn;
    }
  }

  &__body {
    @include flex-between;
  }

  &__kcal {
    font-size: $t-24;
    color: $text-2;
  }

  &__amount {
    display: flex;
    align-items: center;
    width: 260rpx;

    // 分量输入框略显紧凑
    :deep(.c-input) {
      flex: 1;
      height: 64rpx;
    }
  }

  &__unit {
    margin-left: $space-xs;
    font-size: $t-24;
    color: $text-2;
  }
}

.seg {
  display: flex;
  flex-wrap: wrap;
  gap: $space-sm;
}
</style>