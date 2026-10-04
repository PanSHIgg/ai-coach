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
          <CButton block @click="takePhoto">拍摄照片</CButton>
          <CButton class="camera__manual" type="secondary" block @click="pickFromAlbum">从相册选择</CButton>
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
          <image class="camera__preview" :src="imagePath" mode="aspectFill" />

          <!-- 2. 识别中：骨架 -->
          <CSkeleton v-if="recognizing" type="card" class="camera__skeleton" />

          <!-- 3. 识别失败（一项都没返回）：换个角度或手动搜索兜底（§2.4） -->
          <view v-else-if="failed" class="camera__fail">
            <CError text="没识别出来，换个角度再试试" @retry="takePhoto" />
            <CButton class="camera__manual" type="secondary" block @click="pickFromAlbum">
              从相册选择
            </CButton>
            <CButton class="camera__manual" type="ghost" block @click="goManual">
              手动搜索录入
            </CButton>
          </view>

          <!-- 4. 识别结果：每一项都可见、可处置；合计只统计「已确认」项 -->
          <view v-else-if="items.length" class="camera__result">
            <!-- 待处置清单（按 ambiguous / 低置信分别给文案，§2.4 / §6.3.2） -->
            <view v-if="pendingHints.length" class="camera__tips">
              <text v-for="(h, i) in pendingHints" :key="i" class="camera__tip">{{ h }}</text>
            </view>

            <view v-for="(it, i) in items" :key="it.uid" class="item" :class="`item--${statusOf(it)}`">
              <view class="item__head">
                <text class="item__name">{{ primaryName(it) }}</text>
                <text class="item__badge" :class="`item__badge--${badgeKind(it)}`">{{ badgeText(it) }}</text>
              </view>

              <!-- 用户明确跳过：不出分量、不计热量，但仍在列表里可见可撤销 -->
              <view v-if="statusOf(it) === 'skip'" class="item__row">
                <text class="item__note">已跳过，不计入本次记录</text>
                <CButton size="sm" type="ghost" @click="onRestore(i)">撤销</CButton>
              </view>

              <template v-else>
                <view class="item__body">
                  <text class="item__kcal">{{ kcalText(it) }}</text>
                  <view class="item__amount">
                    <CInput v-model="it.amountText" type="digit" placeholder="分量" />
                    <text class="item__unit">g</text>
                  </view>
                </view>

                <!-- 后端已自动采纳但置信度 <0.7：逐项核对后才入账（硬门禁） -->
                <view v-if="needCheck(it)" class="item__row">
                  <text class="item__note">置信度较低，请核对名称与分量</text>
                  <CButton size="sm" type="secondary" @click="onCheck(i)">核对无误</CButton>
                </view>
                <!-- 已由用户从候选中选定：保留原始识别名，另起一行说明选了什么 -->
                <view v-else-if="pickedName(it)" class="item__row">
                  <text class="item__note">已选：{{ pickedName(it) }} · {{ pickedMeta(it) }}</text>
                  <CButton size="sm" type="ghost" @click="onRepick(i)">重选</CButton>
                </view>

                <!-- 召回到候选但不确定（ambiguous）：必须让用户点一个，不许丢弃 -->
                <view v-if="showCandidates(it)" class="cands">
                  <text class="cands__label">没匹配到确切食物，请选一个最接近的：</text>
                  <view
                    v-for="c in candidatesOf(it)"
                    :key="c.food_id"
                    class="cands__item"
                    @tap="onPick(i, c)"
                  >
                    <text class="cands__name">{{ c.name }}</text>
                    <text class="cands__meta">
                      {{ Math.round(c.calories_100g) }} kcal/100g · 相似度 {{ scoreText(c) }}
                    </text>
                  </view>
                </view>
                <text v-else-if="showNoCandidate(it)" class="cands__label">
                  后端暂未回传候选（待联调），可手动填热量或先跳过。
                </text>

                <!-- 手动填热量：食物库里确实没有（§2.4「这是新菜？手动填热量」） -->
                <view v-if="it.action === 'manual'" class="manual">
                  <CField label="食物名称" required :error="it.manualName.trim() ? '' : '请填写名称'">
                    <CInput v-model="it.manualName" placeholder="如：自制牛油果沙拉" :maxlength="128" />
                  </CField>
                  <CField
                    label="热量 (kcal/100g)"
                    required
                    :error="manualKcalError(it)"
                    hint="保存时建为自定义食物（仅本人可见，待审核）"
                  >
                    <CInput v-model="it.manualKcal100" type="digit" placeholder="如：88" />
                  </CField>
                </view>

                <view class="item__actions">
                  <text v-if="it.action !== 'manual'" class="item__link" @tap="onManual(i)">手动填热量</text>
                  <text v-else class="item__link" @tap="onCancelManual(i)">取消手动填写</text>
                  <text class="item__link item__link--muted" @tap="onSkip(i)">跳过这项</text>
                </view>
              </template>
            </view>

            <!-- 合计口径：只累加「已确认」项，与入账项逐条同式计算 -->
            <view class="sum">
              <text class="sum__kcal">已确认合计 {{ totalKcal }} kcal（{{ readyItems.length }} 项）</text>
              <text v-if="pendingItems.length" class="sum__warn">
                另有 {{ pendingItems.length }} 项待确认，未计入合计
              </text>
              <text v-if="skippedItems.length" class="sum__muted">
                已跳过 {{ skippedItems.length }} 项，不会记录
              </text>
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

            <CButton block :disabled="!canSave" :loading="saving" @click="onSave">
              记下来（{{ totalKcal }} kcal · {{ readyItems.length }} 项）
            </CButton>
            <text v-if="blockReason" class="camera__block">{{ blockReason }}</text>
            <view class="camera__repick">
              <CButton type="ghost" block @click="takePhoto">重新拍摄</CButton>
              <CButton type="ghost" block @click="pickFromAlbum">从相册换图</CButton>
            </view>
          </view>
        </template>
      </CCard>
    </template>
  </view>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useUserStore } from '@/stores/user'
import { redirectToLogin } from '@/utils/nav'
import { createMeal, createCustomFood } from '@/api/records'
import { BASE_URL, getToken } from '@/api/request'
import { useToast } from '@/composables/useToast'
import { track } from '@/utils/track'
import { uploadImage } from '@/utils/upload'
import type { Envelope, MatchCandidate, RecognizeData, RecognizedItem } from '@/types/api'

/**
 * 识别项 + 本页处置状态。
 *
 * 数据诚信口径（§6.3.2 + §2.4）：识别返回的**每一项都必须由用户处置**，
 * 只有「已确认（ready）」的项才计入合计并写账；「待确认（pending）」既不计入
 * 合计也不入账，且存在待确认项时保存被硬门禁拦住；「已跳过（skip）」是用户
 * 明示不要，同样不计合计。三种态下的数字口径互不重叠 → 界面合计 === 入账合计。
 */
interface EditableItem extends RecognizedItem {
  /** 稳定 key：部分写入失败后整表 filter 会位移，索引 key 会让输入框与项错位（见 :key="it.uid"） */
  uid: string
  /** 可编辑分量（字符串便于输入框双向绑定） */
  amountText: string
  /** 用户从 candidates 里选定的 food_id；null=尚未选定 */
  pickedId: number | null
  /** 未命中项的出路：none=未处置 / manual=手动填热量（建自定义食物）/ skip=用户明确跳过 */
  action: 'none' | 'manual' | 'skip'
  /** 低置信项已被用户「核对无误」 */
  checked: boolean
  /** 手动填写的食物名称（action=manual） */
  manualName: string
  /** 手动填写的每 100g 热量（action=manual） */
  manualKcal100: string
  /** 已成功写入饮食记录（部分失败时据此从列表剔除，重试不重复入账） */
  saved: boolean
}

type ItemStatus = 'ready' | 'pending' | 'skip'
type PendingReason = 'candidate' | 'unmatched' | 'low' | 'manual'

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

/** 待处置提示文案：ambiguous（没匹配到确切食物）与低置信（置信度较低）分开表述 */
const PENDING_HINTS: Record<PendingReason, string> = {
  candidate: '有 {n} 项没匹配到确切食物，请选一个最接近的（或手动填热量 / 跳过）',
  unmatched: '有 {n} 项在食物库里查不到，这是新菜？手动填热量或先跳过',
  low: '有 {n} 项置信度较低，请核对分量后点「核对无误」',
  manual: '有 {n} 项还没填有效热量（0~1000 kcal/100g）',
}

const userStore = useUserStore()
const toast = useToast()

const imagePath = ref('')
/** 当前照片的 COS 直传 Promise（与识别并行；保存时 await 取公开读 URL，未配置/失败为 null） */
let cosUpload: Promise<string | null> | null = null
const recognizing = ref(false)
const failed = ref(false)
/** 后端 need_confirm：本页门禁改由逐项状态推导，此值只用于埋点回传 */
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

/**
 * 选图入口：拍摄 / 相册分成两个独立按钮（实测合并入口在部分机型只拉起相机）。
 * 拍摄直接拉起微信原生拍照界面（全屏取景 + 快门 + 相册入口 + 反转摄像头）。
 */
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
      // 直传 COS（公开读/私有写；与识别并行，失败不阻断，image_url 回退 null）
      cosUpload = uploadImage(path, 'meal')
      recognize(path)
    },
  })
}

/**
 * 上传图片调用识别接口（multipart/form-data，字段名 image，见 openapi /api/meal/recognize）。
 * 【假设】request.ts 仅封装 JSON 请求，multipart 需走 uni.uploadFile，故此处内联实现，
 * 仅复用 BASE_URL / getToken；按契约解析 items + need_confirm + ambiguous + candidates。
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

/** 本页内自增的项标识（识别一次最多 MAX_ITEMS 条，无需 uuid；每次 recognize() 重置） */
let uidSeed = 0

/** 契约项 → 本页可处置项；对 ambiguous/candidates 缺省（后端尚未回传）保持安全 */
function toEditable(it: RecognizedItem): EditableItem {
  uidSeed += 1
  return {
    ...it,
    uid: `ri-${uidSeed}`,
    amountText: it.amount_g ? String(it.amount_g) : '',
    pickedId: null,
    action: 'none',
    checked: false,
    manualName: it.name || '',
    manualKcal100: '',
    saved: false,
  }
}

async function recognize(path: string) {
  // 识别成功率（分母）：发起一次拍照识别
  track('meal_photo', { meal_type: mealType.value })
  recognizing.value = true
  failed.value = false
  items.value = []
  try {
    const data = await uploadRecognize(path)
    items.value = (data.items || []).map(toEditable)
    needConfirm.value = !!data.need_confirm
    // 一项都没返回才算识别失败；有返回但没匹配上 → 逐项给用户出路，不再静默丢弃
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
      // 数据诚信观测：识别到几项、其中几项无法自动入账
      item_count: items.value.length,
      ambiguous_count: items.value.filter((it) => it.ambiguous === true).length,
      unmatched_count: items.value.filter((it) => it.food_id == null).length,
    })
  }
}

/* ---------- 逐项状态推导 ---------- */

function isLow(it: EditableItem): boolean {
  return (it.confidence ?? 0) < LOW_CONFIDENCE
}
function confidenceText(it: EditableItem): string {
  return `${Math.round((it.confidence ?? 0) * 100)}%`
}
/** 后端把 candidates 填进响应是另一波：字段缺失时一律按「无候选」处理，不崩 */
function candidatesOf(it: EditableItem): MatchCandidate[] {
  return (it.candidates || []).filter((c) => c && typeof c.food_id === 'number')
}
function pickedCandidate(it: EditableItem): MatchCandidate | null {
  if (it.pickedId == null) return null
  return candidatesOf(it).find((c) => c.food_id === it.pickedId) || null
}
function pickedName(it: EditableItem): string {
  return pickedCandidate(it)?.name || ''
}
function pickedMeta(it: EditableItem): string {
  const c = pickedCandidate(it)
  if (!c) return ''
  return `${Math.round(c.calories_100g)} kcal/100g · 相似度 ${scoreText(c)}`
}
function scoreText(c: MatchCandidate): string {
  return `${Math.round((Number(c.score) || 0) * 100)}%`
}
/** 展示名：手动填写用用户输入，其余沿用识别名（选候选时保留原始名，另起一行说明选了什么） */
function primaryName(it: EditableItem): string {
  if (it.action === 'manual') return it.manualName.trim() || it.name || '未命名食物'
  return it.name || '未命名食物'
}
/** 手动填的热量是否合法（0 < kcal ≤ KCAL_MAX，对齐后端 FoodCustomIn） */
function manualValid(it: EditableItem): boolean {
  const kcal = Number(it.manualKcal100)
  return !!it.manualName.trim() && kcal > 0 && kcal <= KCAL_MAX
}
function manualKcalError(it: EditableItem): string {
  if (it.action !== 'manual') return ''
  const kcal = Number(it.manualKcal100)
  if (!kcal || kcal <= 0) return '请填写热量'
  if (kcal > KCAL_MAX) return `需在 0~${KCAL_MAX} kcal/100g`
  return ''
}
/** 后端自动采纳但置信度低 → 需用户逐项核对 */
function needCheck(it: EditableItem): boolean {
  return it.action === 'none' && it.food_id != null && isLow(it) && !it.checked
}
function showCandidates(it: EditableItem): boolean {
  return it.action === 'none' && it.food_id == null && it.pickedId == null && candidatesOf(it).length > 0
}
/**
 * 「后端暂未回传候选」只用于 ambiguous=true 却没带 candidates 的情形（后端尚未联调）；
 * 库里确实没有（ambiguous=false）不该被说成待联调，其出路是手动填热量 / 跳过。
 */
function showNoCandidate(it: EditableItem): boolean {
  return (
    it.action === 'none' &&
    it.food_id == null &&
    it.pickedId == null &&
    it.ambiguous === true &&
    !candidatesOf(it).length
  )
}

/**
 * 三项态的唯一判定入口（合计、徽标、门禁、入账都走它，避免口径分叉）：
 * - skip：用户明确跳过；
 * - ready：手动热量合法 / 后端已采纳且（高置信或已核对）/ 用户已选定候选；
 * - pending：其余一律待确认——不计合计、不入账、拦住保存。
 */
function statusOf(it: EditableItem): ItemStatus {
  if (it.action === 'skip') return 'skip'
  if (it.action === 'manual') return manualValid(it) ? 'ready' : 'pending'
  if (it.food_id != null) return needCheck(it) ? 'pending' : 'ready'
  return it.pickedId != null ? 'ready' : 'pending'
}
function pendingReason(it: EditableItem): PendingReason | null {
  if (statusOf(it) !== 'pending') return null
  if (it.action === 'manual') return 'manual'
  if (it.food_id != null) return 'low'
  return it.ambiguous === true ? 'candidate' : 'unmatched'
}
function badgeKind(it: EditableItem): 'ok' | 'warn' | 'need' | 'muted' {
  const s = statusOf(it)
  if (s === 'skip') return 'muted'
  if (s === 'pending') return 'need'
  if (it.food_id != null && isLow(it)) return 'warn'
  return 'ok'
}
function badgeText(it: EditableItem): string {
  const s = statusOf(it)
  if (s === 'skip') return '已跳过'
  if (s === 'ready') {
    if (it.action === 'manual') return '自定义 · 待审核'
    if (it.pickedId != null) return '已选定'
    return `已确认 ${confidenceText(it)}`
  }
  if (needCheck(it)) return `${confidenceText(it)} 需核对`
  if (it.action === 'manual') return '热量待填'
  return it.food_id == null && !candidatesOf(it).length && it.ambiguous !== true ? '未匹配' : '待确认'
}

/** 每 100g 热量：用户选定候选 > 后端命中项反推 > 用户手动填写 */
function kcalPer100g(it: EditableItem): number {
  const picked = pickedCandidate(it)
  if (picked) return Number(picked.calories_100g) || 0
  if (it.action === 'manual') return Number(it.manualKcal100) || 0
  if (it.food_id != null) return it.amount_g > 0 ? (Number(it.calories) * 100) / it.amount_g : 0
  return 0
}
function amountOf(it: EditableItem): number {
  const g = Number(it.amountText)
  return Number.isFinite(g) && g > 0 ? g : 0
}
/**
 * 单项热量：与后端 createMeal 的重算口径一致（food 的每 100g 热量 × 分量）。
 * 合计就是这些逐条值的和 → 界面显示的每一项数字与入账数字同源。
 */
function itemCalories(it: EditableItem): number {
  const per100 = kcalPer100g(it)
  if (per100 > 0) return Math.round((per100 * amountOf(it)) / 100)
  // 兜底：后端没给 amount_g 以致反推不出每 100g 时，沿用后端返回的该项热量
  return Math.round(Number(it.calories) || 0)
}
function kcalText(it: EditableItem): string {
  const s = statusOf(it)
  if (s === 'skip') return '不记录'
  if (s === 'pending') return '未计入'
  if (!amountOf(it)) return '请填写分量'
  return `${itemCalories(it)} kcal`
}

/* ---------- 聚合视图 ---------- */

const readyItems = computed(() => items.value.filter((it) => statusOf(it) === 'ready'))
const pendingItems = computed(() => items.value.filter((it) => statusOf(it) === 'pending'))
const skippedItems = computed(() => items.value.filter((it) => statusOf(it) === 'skip'))
/** 合计只统计已确认项，且逐条取整后相加（与每条展示的数字完全一致） */
const totalKcal = computed(() => readyItems.value.reduce((sum, it) => sum + itemCalories(it), 0))
const canSave = computed(() => readyItems.value.length > 0 && !pendingItems.value.length)
const blockReason = computed(() => {
  if (pendingItems.value.length) {
    return `还有 ${pendingItems.value.length} 项待确认：选一个候选 / 手动填热量 / 跳过，处理完才能记录`
  }
  if (!readyItems.value.length) return '没有可记录的食物，可换张照片或手动搜索录入'
  return ''
})
const pendingHints = computed(() => {
  const counts = new Map<PendingReason, number>()
  for (const it of items.value) {
    const r = pendingReason(it)
    if (r) counts.set(r, (counts.get(r) || 0) + 1)
  }
  return (['candidate', 'low', 'unmatched', 'manual'] as PendingReason[])
    .filter((r) => counts.has(r))
    .map((r) => PENDING_HINTS[r].replace('{n}', String(counts.get(r))))
})

/* ---------- 处置动作 ---------- */

function onPick(i: number, c: MatchCandidate) {
  const it = items.value[i]
  if (!it) return
  it.pickedId = c.food_id
  it.action = 'none'
  it.checked = true
}
function onRepick(i: number) {
  const it = items.value[i]
  if (!it) return
  it.pickedId = null
  it.checked = false
}
function onCheck(i: number) {
  const it = items.value[i]
  if (!it) return
  it.checked = true
}
function onManual(i: number) {
  const it = items.value[i]
  if (!it) return
  it.action = 'manual'
  if (!it.manualKcal100 && it.food_id != null && it.amount_g > 0) {
    it.manualKcal100 = String(Math.round((Number(it.calories) * 100) / it.amount_g))
  }
}
function onCancelManual(i: number) {
  const it = items.value[i]
  if (!it) return
  it.action = 'none'
  it.manualKcal100 = ''
}
function onSkip(i: number) {
  const it = items.value[i]
  if (!it) return
  it.action = 'skip'
}
function onRestore(i: number) {
  const it = items.value[i]
  if (!it) return
  // 撤销跳过后回落到原本的逐项判定：低置信仍需核对、未匹配仍需出路
  it.action = 'none'
}

/* ---------- 写入 ---------- */

/**
 * 写入饮食记录（source=1 拍照；手动填热量项建为自定义食物后按 source=3 手动记）。
 *
 * 只写 statusOf==='ready' 的项，且保存前再校验一次门禁（按钮虽已禁用，仍防状态竞态）：
 * 入账项与界面「已确认合计」同源同式，因此 记下来的 kcal === 界面显示的合计。
 */
async function onSave() {
  if (!canSave.value) {
    toast.error({ title: blockReason.value || '没有可记录的食物' })
    return
  }
  const plan = readyItems.value
  for (const it of plan) {
    const g = amountOf(it)
    if (!g) {
      toast.error({ title: `「${primaryName(it)}」请填写正确的分量` })
      return
    }
    if (g > AMOUNT_MAX) {
      toast.error({ title: `分量需在 0~${AMOUNT_MAX}g` })
      return
    }
    const foodId = it.action === 'manual' ? null : it.food_id ?? it.pickedId
    if (it.action !== 'manual' && foodId == null) {
      toast.error({ title: `「${primaryName(it)}」还没选定食物` })
      return
    }
  }

  saving.value = true
  let done = 0
  try {
    // 等待 COS 直传完成，取公开读 URL（未配置/失败 → null，不阻断记录）
    const imageUrl = cosUpload ? await cosUpload : null
    for (const it of plan) {
      let foodId = it.food_id ?? it.pickedId
      if (it.action === 'manual') {
        const created = await createCustomFood({
          name: primaryName(it),
          calories_100g: Number(it.manualKcal100),
        })
        foodId = created.id
      }
      await createMeal({
        meal_type: mealType.value,
        food_id: Number(foodId),
        amount_g: amountOf(it),
        // 拍照链路的自定义食物由用户手填热量，按手动口径入账
        source: it.action === 'manual' ? 3 : 1,
        image_url: imageUrl,
      })
      it.saved = true
      done += 1
    }
    toast.success({ title: `已记下 ${done} 项 · ${totalKcal.value} kcal` })
    // 广播识别结果：吃什么页 uni.$on('eat:recognized') 接收（见 pages/eat.vue）
    // 只广播真正入账的项，待确认/跳过项不冒充「已识别」
    uni.$emit('eat:recognized', { foods: plan.map((it) => primaryName(it)) })
    setTimeout(() => uni.navigateBack(), 600)
  } catch (e) {
    // 部分写入失败：已入账项移出列表，剩余项留在页面上可重试（不重复入账）。
    // 「剩余」只统计**本次要入账**（ready）且尚未写成的项——pending/skip 项本来就不入账，
    // 用整表长度会把它们算进去，报出一个偏大且无意义的数字。
    const remaining = readyItems.value.filter((it) => !it.saved).length
    items.value = items.value.filter((it) => !it.saved)
    if (done) {
      toast.error({ title: `已记下 ${done} 项，剩余 ${remaining} 项请重试` })
    }
    // 其余错误信息已由 request 封装 toast
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

  &__tips {
    margin-bottom: $space-md;
  }

  &__tip {
    display: block;
    margin-bottom: $space-xs;
    padding: $space-sm $space-md;
    font-size: $t-22;
    color: $warn;
    background: rgba($warn, 0.1);
    border-radius: $radius-sm;
  }

  &__block {
    display: block;
    margin-top: $space-sm;
    font-size: $t-22;
    color: $danger;
  }

  &__manual {
    margin-top: $space-sm;
  }

  // 识别结果页「重新拍摄 / 从相册换图」并排
  &__repick {
    display: flex;
    gap: $space-sm;
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

  // 待确认项左侧标色，让「没处置完」在列表里一眼可见
  &--pending {
    border-left: 6rpx solid $warn;
    padding-left: $space-sm;
  }

  &--skip {
    opacity: 0.55;
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
    flex-shrink: 0;
    margin-left: $space-sm;
    padding: 2rpx $space-xs;
    font-size: $t-22;
    border-radius: $radius-sm;

    &--ok {
      color: $success;
      background: rgba($success, 0.1);
    }

    &--warn {
      color: $warn;
      background: rgba($warn, 0.1);
    }

    &--need {
      color: $danger;
      background: rgba($danger, 0.1);
    }

    &--muted {
      color: $text-3;
      background: $bg;
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

  &__row {
    @include flex-between;

    margin-top: $space-xs;
  }

  &__note {
    flex: 1;
    min-width: 0;
    font-size: $t-22;
    color: $text-2;
  }

  &__actions {
    display: flex;
    gap: $space-lg;
    margin-top: $space-xs;
  }

  &__link {
    font-size: $t-24;
    color: $brand;

    &--muted {
      color: $text-3;
    }
  }
}

.cands {
  margin-top: $space-xs;
  padding: $space-sm;
  background: $bg;
  border-radius: $radius-sm;

  &__label {
    display: block;
    margin-bottom: $space-xs;
    font-size: $t-22;
    color: $warn;
  }

  &__item {
    @include flex-between;

    padding: $space-xs 0;

    &:not(:last-child) {
      @include hairline(bottom);
    }
  }

  &__name {
    font-size: $t-26;
    color: $text-1;
  }

  &__meta {
    flex-shrink: 0;
    margin-left: $space-sm;
    font-size: $t-22;
    color: $text-2;
  }
}

.manual {
  margin-top: $space-sm;
  padding: $space-sm;
  background: $bg;
  border-radius: $radius-sm;
}

.sum {
  margin: $space-md 0;
  padding: $space-sm $space-md;
  background: $bg;
  border-radius: $radius-sm;

  &__kcal {
    display: block;
    font-size: $t-28;
    font-weight: 500;
    color: $brand;
  }

  &__warn {
    display: block;
    margin-top: 2rpx;
    font-size: $t-22;
    color: $warn;
  }

  &__muted {
    display: block;
    margin-top: 2rpx;
    font-size: $t-22;
    color: $text-3;
  }
}

.seg {
  display: flex;
  flex-wrap: wrap;
  gap: $space-sm;
}
</style>
