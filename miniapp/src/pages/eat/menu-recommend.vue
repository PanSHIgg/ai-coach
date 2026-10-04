<template>
  <view class="menu-rec">
    <CNoPermission v-if="!userStore.isLogined" text="登录后使用菜单识别推荐" @action="goLogin" />

    <CCard v-else title="拍菜单，AI 帮你挑着吃" class="menu-rec__card">
      <!-- 1. 未选图：引导拍照 / 相册 -->
      <view v-if="!imagePath" class="menu-rec__empty">
        <image class="menu-rec__icon" src="/static/icons/ic-camera-white.png" mode="aspectFit" />
        <text class="menu-rec__hint">拍下食堂 / 外卖菜单，识别后直接给推荐组合</text>
        <CButton block @click="takePhoto">拍摄菜单</CButton>
        <CButton block type="secondary" class="menu-rec__gap" @click="pickFromAlbum">从相册选择</CButton>
      </view>

      <template v-else>
        <image class="menu-rec__preview" :src="imagePath" mode="aspectFill" />

        <CSkeleton v-if="recognizing" type="card" />

        <view v-else-if="failed" class="menu-rec__fail">
          <CError text="没识别出来，换个角度再试试" @retry="takePhoto" />
          <CButton block type="secondary" class="menu-rec__gap" @click="pickFromAlbum">从相册换图</CButton>
        </view>

        <!-- 2. 识别结果 + AI 推荐方案卡（§5.2-3/4） -->
        <template v-else-if="names.length">
          <view class="menu-rec__recogn">
            <text class="menu-rec__recogn-title">AI 识别到：</text>
            <view class="menu-rec__chips">
              <text v-for="(n, i) in names" :key="i" class="menu-rec__chip">{{ n }}</text>
            </view>
            <CButton size="sm" type="ghost" class="menu-rec__repick" @click="takePhoto">重新拍摄</CButton>
          </view>

          <view class="menu-rec__opts-title">
            <text class="menu-rec__opts-name">AI 推荐 · {{ mealText }}</text>
          </view>
          <CSkeleton v-if="recLoading" type="card" />
          <CError v-else-if="recError" @retry="loadRecommend" />
          <CEmpty
            v-else-if="!options.length"
            icon="empty-chat"
            text="这几个菜暂时没匹配到推荐，换个菜单试试"
          />
          <view v-else class="opts">
            <view v-for="(opt, i) in options" :key="i" class="opt">
              <view class="opt__bar" :class="`opt__bar--${levelOf(opt.calories)}`" />
              <view class="opt__main">
                <view class="opt__head">
                  <text class="opt__name">{{ opt.name }}</text>
                  <text class="opt__tag">{{ LEVEL_TEXT[levelOf(opt.calories)] }}</text>
                </view>
                <text class="opt__kcal">约 {{ opt.calories }} kcal</text>
                <text class="opt__reason">{{ opt.reason }}</text>
                <CButton
                  size="sm"
                  :loading="pickingIndex === i"
                  @click="pickOption(opt, i)"
                >
                  选这个，记下来
                </CButton>
              </view>
            </view>
          </view>
        </template>
      </template>
    </CCard>
  </view>
</template>

<script setup lang="ts">
/**
 * 菜单识别 · AI 推荐（§5.2「菜单拍照识别+推荐」独立页）
 * 链路：拍菜单 → VLM 识别菜品名 → POST /api/ai/recommend { meal_type, items }
 *       → 按识别的菜出绿/黄/红方案卡 →「选这个，记下来」（source=4 AI 推荐）。
 * 与拍照记录页（record/camera）分离：本页只做「识别+推荐」，逐项热量记录走原拍照页。
 */
import { computed, ref } from 'vue'
import { useUserStore } from '@/stores/user'
import { useAccountStore } from '@/stores/account'
import { useToast } from '@/composables/useToast'
import { useRecordCombo } from '@/composables/useRecordCombo'
import { redirectToLogin } from '@/utils/nav'
import { recommend } from '@/api/ai'
import { BASE_URL, getToken } from '@/api/request'
import type { Envelope, RecommendOption, RecognizeData } from '@/types/api'

type Level = 'good' | 'mid' | 'bad'
const LEVEL_TEXT: Record<Level, string> = { good: '推荐', mid: '可接受', bad: '建议少吃 / 替代' }

/** 单餐绝对阈值（kcal）：≥800 红 / ≥600 黄；额度口径以 accountStore.left 为准 */
const MEAL_KCAL_HIGH = 800
const MEAL_KCAL_MID = 600

const userStore = useUserStore()
const accountStore = useAccountStore()
const toast = useToast()
const { recordCombo } = useRecordCombo()

const imagePath = ref('')
const recognizing = ref(false)
const failed = ref(false)
/** 识别到的菜品名（同时作为推荐接口的 items） */
const names = ref<string[]>([])

const hour = new Date().getHours()
const mealType = ref<1 | 2 | 3 | 4>(hour < 10 ? 1 : hour < 15 ? 2 : hour < 20 ? 3 : 4)
const mealText = computed(() => ({ 1: '早餐', 2: '午餐', 3: '晚餐', 4: '加餐' })[mealType.value])

const options = ref<RecommendOption[]>([])
const recLoading = ref(false)
const recError = ref(false)
const pickingIndex = ref(-1)

function levelOf(calories: number): Level {
  const left = accountStore.today ? Math.round(accountStore.left) : 0
  if (calories >= MEAL_KCAL_HIGH) return 'bad'
  if (left > 0 && calories > left) return 'bad'
  if (calories >= MEAL_KCAL_MID) return 'mid'
  if (left > 0 && calories > left * 0.6) return 'mid'
  return 'good'
}

function takePhoto() {
  choosePic('camera')
}
function pickFromAlbum() {
  choosePic('album')
}
function choosePic(sourceType: 'camera' | 'album') {
  uni.chooseImage({
    count: 1,
    sizeType: ['compressed'],
    sourceType: [sourceType],
    success: (res) => {
      const path = (res.tempFilePaths as string[])[0]
      if (!path) return
      imagePath.value = path
      names.value = []
      options.value = []
      recognize(path)
    },
  })
}

/** multipart 识别（与 camera.vue 同款内联实现：request.ts 只封装了 JSON） */
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
        } catch {
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
  names.value = []
  try {
    const data = await uploadRecognize(path)
    names.value = (data.items || [])
      .map((it) => it.name)
      .filter((n): n is string => !!n && !!n.trim())
      .map((n) => n.trim())
    if (!names.value.length) {
      failed.value = true
      return
    }
    await loadRecommend()
  } catch (e) {
    failed.value = true
    toast.error({ title: (e as Error).message || '识别失败，换个角度或重试' })
  } finally {
    recognizing.value = false
  }
}

/** 按识别菜名出推荐（后端四级匹配 food 库，未命中的忽略） */
async function loadRecommend() {
  recLoading.value = true
  recError.value = false
  try {
    const data = await recommend({ meal_type: mealType.value, items: names.value })
    options.value = data?.options ?? []
  } catch (e) {
    recError.value = true
    options.value = []
  } finally {
    recLoading.value = false
  }
}

async function pickOption(opt: RecommendOption, index: number) {
  pickingIndex.value = index
  try {
    const count = await recordCombo(opt.name, opt.calories, mealType.value, 4)
    if (!count) {
      toast.info({ title: '未匹配到食物，请在「首页·记录」手动录入' })
      return
    }
    toast.success({ title: '已记下来' })
    accountStore.refresh()
  } catch (e) {
    toast.error({ title: (e as Error).message || '记录失败，请重试' })
  } finally {
    pickingIndex.value = -1
  }
}

function goLogin() {
  redirectToLogin()
}
</script>

<style lang="scss" scoped>
.menu-rec {
  padding: $space-md;

  &__card {
    margin-bottom: $space-md;
  }

  &__empty {
    @include flex-center(column);

    padding: $space-lg 0;
  }

  &__icon {
    width: 140rpx;
    height: 140rpx;
    margin-bottom: $space-md;
    background: $bg;
    border-radius: 50%;
  }

  &__hint {
    margin-bottom: $space-lg;
    font-size: $t-26;
    color: $text-2;
  }

  &__gap {
    margin-top: $space-sm;
  }

  &__preview {
    width: 100%;
    height: 360rpx;
    margin-bottom: $space-md;
    border-radius: $radius;
    background: $bg;
  }

  &__fail {
    margin-bottom: $space-md;
  }

  &__recogn {
    margin-bottom: $space-md;
  }

  &__recogn-title {
    font-size: $t-26;
    color: $text-2;
  }

  &__chips {
    display: flex;
    flex-wrap: wrap;
    gap: $space-sm;
    margin-top: $space-sm;
  }

  &__chip {
    padding: 4rpx $space-sm;
    font-size: $t-24;
    color: $brand-dark;
    background: rgba($brand, 0.1);
    border-radius: $radius-sm;
  }

  &__repick {
    margin-top: $space-sm;
    align-self: flex-start;
  }

  &__opts-title {
    margin-bottom: $space-sm;
  }

  &__opts-name {
    font-size: $t-28;
    font-weight: 500;
    color: $text-1;
  }
}

// 方案卡（同吃什么页 .opt：左色条 + 等级标签）
.opts {
  display: flex;
  flex-direction: column;
  gap: $space-sm;
}

.opt {
  display: flex;
  overflow: hidden;
  background: $bg;
  border: 1rpx solid $disabled;
  border-radius: $radius;

  &__bar {
    flex: none;
    width: 8rpx;
    background: $success;

    &--mid {
      background: $warn;
    }

    &--bad {
      background: $danger;
    }
  }

  &__main {
    flex: 1;
    padding: $space-md;
  }

  &__head {
    @include flex-between;

    margin-bottom: $space-xs;
  }

  &__name {
    flex: 1;
    font-size: $t-28;
    font-weight: 500;
    color: $text-1;
  }

  &__tag {
    margin-left: $space-sm;
    font-size: $t-22;
    color: $text-2;
  }

  &__kcal {
    display: block;
    font-size: $t-26;
    font-weight: 700;
    color: $text-1;
  }

  &__reason {
    display: block;
    margin: $space-xs 0 $space-sm;
    font-size: $t-22;
    color: $text-2;
  }

  &__btn {
    align-self: flex-start;
  }
}
</style>
