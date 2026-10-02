<template>
  <view class="camera">
    <!-- 未登录（§5.8 无权限态） -->
    <CNoPermission v-if="!userStore.isLogined" text="登录后使用拍照记录" @action="goLogin" />

    <template v-else>
      <CCard title="拍照识别" class="camera__card">
        <!-- 1. 未选图：引导拍照 / 选择 -->
        <view v-if="!imagePath" class="camera__empty">
          <image class="camera__empty-icon" src="/static/illustrations/empty-camera.png" mode="aspectFit" />
          <text class="camera__empty-text">拍下这一餐，AI 帮你识别热量</text>
          <CButton block @click="choosePic">选择 / 拍摄照片</CButton>
          <CButton class="camera__manual" type="ghost" block @click="goManual">手动搜索录入</CButton>
          <CButton class="camera__manual" type="ghost" block @click="customVisible = !customVisible">
            {{ customVisible ? '收起自定义食物' : '食物库查不到？新建自定义食物' }}
          </CButton>

          <!-- 食物库查不到 → 手动填名称 + 热量，新建自定义食物（仅本人可见，待审核） -->
          <view v-if="customVisible" class="custom">
            <CField label="食物名称" required>
              <CInput v-model="cName" placeholder="如：自制牛油果沙拉" :maxlength="128" />
            </CField>
            <CField label="热量 (kcal/100g)" required>
              <CInput v-model="cCalories" type="digit" placeholder="如：88" />
            </CField>
            <CField label="本次分量 (g)" required>
              <CInput v-model="cAmount" type="digit" placeholder="如：150" />
            </CField>
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
            <CButton block :loading="savingCustom" @click="onCreateCustom">保存并记录</CButton>
          </view>
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

    <!-- #ifdef H5 -->
    <!-- H5 无微信原生相机：自绘取景界面（对齐图1：全屏取景 + 相册 / 快门 / 反转摄像头） -->
    <view v-if="h5CamOn" class="h5cam">
      <view id="h5camStage" class="h5cam__stage">
        <text v-if="h5CamError" class="h5cam__hint">浏览器未授权摄像头，可从相册选择</text>
      </view>
      <view class="h5cam__bar">
        <view class="h5cam__act" @click="h5FromAlbum">
          <image class="h5cam__icon" src="/static/icons/ic-album.svg" mode="aspectFit" />
        </view>
        <view class="h5cam__shutter" @click="h5Shoot" />
        <view class="h5cam__act" @click="h5Flip">
          <image class="h5cam__icon" src="/static/icons/ic-flip-camera.svg" mode="aspectFit" />
        </view>
      </view>
      <text class="h5cam__back" @click="h5Close">‹</text>
    </view>
    <!-- #endif -->
  </view>
</template>

<script setup lang="ts">
import { ref, nextTick, onBeforeUnmount } from 'vue'
import { useUserStore } from '@/stores/user'
import { redirectToLogin } from '@/utils/nav'
import { createMeal, createCustomFood } from '@/api/records'
import { BASE_URL, getToken } from '@/api/request'
import { useToast } from '@/composables/useToast'
import { track } from '@/utils/track'
import { uploadImage } from '@/utils/upload'
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

/** 自定义食物每 100g 热量上界（对齐后端 FoodCustomIn：0 < calories_100g ≤ 1000） */
const KCAL_MAX = 1000

const userStore = useUserStore()
const toast = useToast()

const imagePath = ref('')
/** 当前照片的 COS 直传 Promise（与识别并行；保存时 await 取公开读 URL，未配置/失败为 null） */
let cosUpload: Promise<string | null> | null = null
const recognizing = ref(false)
const failed = ref(false)
const needConfirm = ref(false)
const items = ref<EditableItem[]>([])
const saving = ref(false)

// 自定义食物表单（食物库查不到 → 手动填名称 + 热量）
const customVisible = ref(false)
const cName = ref('')
const cCalories = ref('')
const cAmount = ref('')
const savingCustom = ref(false)

// 默认餐次按当前时段推断
const hour = new Date().getHours()
const mealType = ref<1 | 2 | 3 | 4>(hour < 10 ? 1 : hour < 15 ? 2 : hour < 20 ? 3 : 4)

/** 选中/拍到照片后统一处理：预览 + COS 直传 + 识别 */
function onPicked(path: string) {
  if (!path) return
  imagePath.value = path
  // 直传 COS（公开读/私有写；与识别并行，失败不阻断，image_url 回退 null）
  cosUpload = uploadImage(path, 'meal')
  recognize(path)
}

/**
 * 拍摄照片：直接拉起原生拍照界面（全屏取景 + 快门 + 相册入口 + 反转摄像头），
 * 不再弹「拍照 / 从相册选择」二选一。
 * 小程序走微信原生相机；H5 无原生相机，走自绘取景界面（见 h5cam，对齐图1）。
 */
function choosePic() {
  // #ifdef H5
  openH5Camera()
  // #endif
  // #ifndef H5
  uni.chooseImage({
    count: 1,
    sizeType: ['compressed'],
    sourceType: ['camera'],
    success: (res) => onPicked((res.tempFilePaths as string[])[0]),
  })
  // #endif
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
  // 识别成功率（分母）：发起一次拍照识别
  track('meal_photo', { meal_type: mealType.value })
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
    // 识别成功率（分子/分母）：回传结果，供报表聚合 success/confidence/need_confirm
    const confidence = items.value.reduce((max, it) => Math.max(max, it.confidence ?? 0), 0)
    track('ai_recognize', {
      success: !failed.value && items.value.length > 0,
      confidence: Number(confidence.toFixed(4)),
      need_confirm: needConfirm.value,
    })
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
    // 等待 COS 直传完成，取公开读 URL（未配置/失败 → null，不阻断记录）
    const imageUrl = cosUpload ? await cosUpload : null
    for (const it of matched) {
      await createMeal({
        meal_type: mealType.value,
        food_id: it.food_id as number,
        amount_g: Number(it.amountText),
        source: 1,
        image_url: imageUrl,
      })
    }
    toast.success({ title: '已记下来' })
    // 广播识别结果：吃什么页 uni.$on('eat:recognized') 接收（见 pages/eat.vue）
    uni.$emit('eat:recognized', { foods: items.value.map((i) => i.name) })
    setTimeout(() => uni.navigateBack(), 600)
  } catch (e) {
    // 错误信息已由 request 封装 toast
  } finally {
    saving.value = false
  }
}

/** 新建自定义食物并直接记入（source=3 手动）；食物仅本人可见、标记待审核 */
async function onCreateCustom() {
  const name = cName.value.trim()
  const kcal = Number(cCalories.value)
  const g = Number(cAmount.value)
  if (!name) {
    toast.error({ title: '请填写食物名称' })
    return
  }
  if (!kcal || kcal <= 0 || kcal > KCAL_MAX) {
    toast.error({ title: `热量需在 0~${KCAL_MAX} kcal/100g` })
    return
  }
  if (!g || g <= 0) {
    toast.error({ title: '请填写正确的分量' })
    return
  }
  if (g > AMOUNT_MAX) {
    toast.error({ title: `分量需在 0~${AMOUNT_MAX}g` })
    return
  }
  savingCustom.value = true
  try {
    const food = await createCustomFood({ name, calories_100g: kcal })
    await createMeal({
      meal_type: mealType.value,
      food_id: food.id,
      amount_g: g,
      source: 3,
      image_url: null,
    })
    toast.success({ title: '已新建并记下来' })
    // 广播：吃什么页 uni.$on('eat:recognized') 接收（见 pages/eat.vue）
    uni.$emit('eat:recognized', { foods: [food.name] })
    setTimeout(() => uni.navigateBack(), 600)
  } catch (e) {
    // 错误信息已由 request 封装 toast
  } finally {
    savingCustom.value = false
  }
}

function goManual() {
  uni.redirectTo({ url: '/pages/record/food-list' })
}
function goLogin() {
  redirectToLogin()
}

// #ifdef H5
/* ---------- H5 自绘相机（对齐图1：全屏取景 + 相册 / 快门 / 反转摄像头） ---------- */
const h5CamOn = ref(false)
const h5CamError = ref(false)
const h5Facing = ref<'environment' | 'user'>('environment')
let h5Stream: MediaStream | null = null
let h5Video: HTMLVideoElement | null = null

function h5StopStream() {
  if (h5Stream) {
    h5Stream.getTracks().forEach((t) => t.stop())
    h5Stream = null
  }
  if (h5Video) h5Video.srcObject = null
}

function h5Close() {
  h5CamOn.value = false
  h5CamError.value = false
  h5StopStream()
}

/** 打开取景界面并启动摄像头（getUserMedia 需 https 或 localhost） */
async function openH5Camera() {
  h5CamOn.value = true
  await nextTick()
  await h5StartStream()
}

async function h5StartStream() {
  h5StopStream()
  // 非安全上下文（http 非 localhost）或无摄像头设备时 mediaDevices 可能不存在
  if (!navigator.mediaDevices?.getUserMedia) {
    h5CamError.value = true
    return
  }
  try {
    h5Stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: h5Facing.value },
      audio: false,
    })
  } catch (e) {
    h5CamError.value = true
    return
  }
  const stage = document.getElementById('h5camStage')
  if (!stage) return
  if (!h5Video) {
    h5Video = document.createElement('video')
    h5Video.setAttribute('autoplay', '')
    h5Video.setAttribute('playsinline', '')
    h5Video.setAttribute('muted', '')
    h5Video.style.cssText =
      'width:100%;height:100%;object-fit:cover;display:block;background:#000;'
    stage.appendChild(h5Video)
  }
  // 前置摄像头按镜像显示（与原生自拍取景一致）
  h5Video.style.transform = h5Facing.value === 'user' ? 'scaleX(-1)' : ''
  h5Video.srcObject = h5Stream
  void h5Video.play().catch(() => {})
  h5CamError.value = false
}

/** 反转摄像头（前置 / 后置） */
function h5Flip() {
  h5Facing.value = h5Facing.value === 'environment' ? 'user' : 'environment'
  void h5StartStream()
}

/** 快门：把当前取景帧画到 canvas，导出 blob URL 作为照片 */
function h5Shoot() {
  const v = h5Video
  if (!v || !v.videoWidth) return
  const canvas = document.createElement('canvas')
  canvas.width = v.videoWidth
  canvas.height = v.videoHeight
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  ctx.drawImage(v, 0, 0)
  canvas.toBlob(
    (blob) => {
      if (!blob) return
      const url = URL.createObjectURL(blob)
      h5Close()
      onPicked(url)
    },
    'image/jpeg',
    0.92,
  )
}

/** 相册：浏览器无系统相册 UI，退化为文件选择 */
function h5FromAlbum() {
  const input = document.createElement('input')
  input.type = 'file'
  input.accept = 'image/*'
  input.onchange = () => {
    const f = input.files && input.files[0]
    if (!f) return
    const url = URL.createObjectURL(f)
    h5Close()
    onPicked(url)
  }
  input.click()
}

onBeforeUnmount(h5Close)
// #endif
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
    width: 176rpx;
    height: 176rpx;
    margin-bottom: $space-md;
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
    background: rgba($warn, 0.1);
    border-radius: $radius-sm;
  }

  &__manual {
    margin-top: $space-sm;
  }
}

.custom {
  width: 100%;
  margin-top: $space-md;
  padding-top: $space-md;
  text-align: left;

  @include hairline(top);
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

/* #ifdef H5 */
/* ---------- H5 自绘相机（对齐图1） ---------- */
.h5cam {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  left: 0;
  z-index: 999;
  display: flex;
  flex-direction: column;
  background: #000;

  &__stage {
    position: relative;
    flex: 1;
    overflow: hidden;
    background: #000;
  }

  &__hint {
    position: absolute;
    top: 50%;
    left: 0;
    width: 100%;
    padding: 0 $space-lg;
    font-size: $t-26;
    color: #fff;
    text-align: center;
    transform: translateY(-50%);
  }

  &__bar {
    @include flex-center(row);

    height: 220rpx;
    background: #000;
  }

  &__act {
    @include flex-center(row);

    width: 96rpx;
    height: 96rpx;
  }

  &__icon {
    width: 56rpx;
    height: 56rpx;
  }

  &__shutter {
    width: 144rpx;
    height: 144rpx;
    margin: 0 120rpx;
    border-radius: 50%;
    background: #fff;
  }

  &__back {
    position: absolute;
    top: $space-md;
    left: $space-md;
    font-size: 64rpx;
    line-height: 1;
    color: #fff;
  }
}
/* #endif */
</style>
