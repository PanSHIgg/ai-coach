<template>
  <view class="eat">
    <!-- 1. 顶部栏（§5.2-1：标题 + 🔔；消息二期接入） -->
    <CTopBar title="吃什么" @bell="onNotice" />

    <!-- 2. AI 帮我找吃的：拍摄 / 相册 / 语音三入口（§5.2-2；拍摄/相册拆两键，实测合并入口部分机型只拉相机） -->
    <view class="eat__entry">
      <text class="eat__entry-label">AI 帮我找吃的</text>
      <view class="eat__entry-row">
        <CButton class="eat__entry-btn" size="md" @click="takePhoto">拍摄照片</CButton>
        <CButton class="eat__entry-btn" size="md" @click="pickFromAlbum">选择照片</CButton>
        <CButton
          class="eat__entry-btn"
          size="md"
          type="secondary"
          :loading="voice.transcribing.value"
          @click="onVoice"
        >
          {{ voiceLabel }}
        </CButton>
      </view>
      <!-- 语音链路常驻提示（useVoice.notice）：toast 1.5s 即消失，「语音录入暂未支持 / 请手动输入」
           这类结论要留在页面上，否则用户只会反复点同一个没接 ASR 的按钮（G4 异常恢复口径） -->
      <text v-if="voice.notice.value" class="eat__entry-notice">{{ voice.notice.value }}</text>
    </view>

    <!-- 3. 识别结果区（§5.2-3）：本页拍照/语音识别后原地展示，并驱动下方推荐卡 -->
    <view class="eat__recogn">
      <template v-if="recognizing">
        <text class="eat__recogn-title">识别中…</text>
      </template>
      <template v-else-if="recognized.length">
        <text class="eat__recogn-title">AI 识别到：</text>
        <view class="eat__chips">
          <text v-for="(food, i) in recognized" :key="i" class="eat__chip">{{ food }}</text>
        </view>
        <text class="eat__clear" @tap="clearRecognized">清空</text>
      </template>
      <CEmpty
        v-else
        icon="empty-food"
        text="还没有识别结果，拍张菜单或货架试试"
        button-text="去拍照"
        @action="takePhoto"
      />
    </view>

    <!-- 4. AI 推荐方案卡（§5.2-4）：左侧色条标识健康等级；识别完成后自动滚到这里 -->
    <view id="eat-recommend">
      <CCard :title="`AI 推荐 · ${mealText}`" class="eat__card">
        <CSkeleton v-if="recLoading" type="card" />
        <CError v-else-if="recError" @retry="loadRecommend" />
        <CEmpty
          v-else-if="!options.length"
          icon="empty-chat"
          text="暂无推荐方案"
          button-text="重新推荐"
          @action="loadRecommend"
        />
        <view v-else class="opts">
        <view v-for="(opt, i) in options" :key="i" class="opt">
          <!-- 左侧健康等级色条（绿/黄/红，§5.2-4）：等级读后端 reason 前缀 -->
          <view class="opt__bar" :class="`opt__bar--${levelOf(opt)}`" />
          <view class="opt__main">
            <view class="opt__head">
              <text class="opt__name">{{ opt.name }}</text>
              <text class="opt__tag">{{ LEVEL_TEXT[levelOf(opt)] }}</text>
            </view>
            <text class="opt__kcal">约 {{ opt.calories }} kcal</text>
            <text class="opt__reason">{{ reasonBody(opt.reason) }}</text>
              <CButton
                class="opt__btn"
                size="sm"
                :loading="pickingIndex === i"
                @click="pickOption(opt, i)"
              >
                选这个，记下来
              </CButton>
            </view>
          </view>
        </view>
      </CCard>
    </view>

    <!-- 5. 今天还剩 X kcal（§5.2-5）：接口不可用则整体隐藏，不报错不白屏 -->
    <view v-if="showLeft" class="eat__left">
      <CSkeleton v-if="leftLoading" :rows="2" />
      <template v-else>
        <view class="eat__left-row">
          <text class="eat__left-text">今天还剩</text>
          <text class="eat__left-num" :class="{ 'eat__left-num--over': leftValue < 0 }">
            {{ fmt(leftValue) }}
          </text>
          <text class="eat__left-text">kcal</text>
        </view>
        <CButton size="sm" type="secondary" @click="onAskCoach">问教练：这个菜油多吗？</CButton>
      </template>
    </view>

    <!-- 6. 标准减脂餐（§5.2-6）：静态 SKU 数据（Phase 3 接 sku/catalog），右侧 + 直接加入今日摄入 -->
    <CCard title="标准减脂餐（直接选）" class="eat__card">
      <view v-for="(meal, i) in STANDARD_MEALS" :key="meal.name" class="sku">
        <view class="sku__main">
          <text class="sku__name">{{ meal.name }}</text>
          <text class="sku__meta">{{ meal.range }} ¥{{ meal.price }}</text>
        </view>
        <CButton
          size="sm"
          type="secondary"
          :loading="addingIndex === i"
          @click="addStandard(meal, i)"
        >
          +
        </CButton>
      </view>
      <text class="eat__link" @tap="onMoreStandard">查看全部标准餐 ›</text>
    </CCard>

    <!-- 7. 附近商家比价（§5.2-7）：标准套餐比价卡片（G5） -->
    <CCard title="附近商家比价（显示标准套餐）" class="eat__card">
      <CSkeleton v-if="cmpLoading" type="card" />
      <CError v-else-if="cmpError" @retry="loadCompare" />
      <CEmpty
        v-else-if="!cmpItems.length"
        icon="empty-store"
        text="附近暂无在售该标准套餐的商家"
        button-text="查看附近商家"
        @action="goMerchants"
      />
      <view v-else class="cmp">
        <view v-for="m in cmpItems" :key="m.merchant_id" class="cmp__item">
          <view class="cmp__head">
            <text class="cmp__name">{{ m.name }}</text>
            <text class="cmp__dist">{{ fmtDistance(m.distance) }}</text>
          </view>
          <view class="cmp__meta">
            <image class="cmp__star" src="/static/icons/ic-star.png" mode="aspectFit" />
            <text class="cmp__rating">{{ m.rating.toFixed(1) }}</text>
          </view>
          <view class="cmp__sku">
            <text class="cmp__sku-name">{{ m.sku_name }}</text>
            <text class="cmp__price">¥{{ m.price }}</text>
            <text v-if="m.coupon_amount > 0" class="cmp__coupon">可用{{ m.coupon_amount }}元券</text>
          </view>
          <view class="cmp__actions">
            <CButton size="sm" @click="goBook(m)">预约</CButton>
            <CButton size="sm" type="secondary" @click="goMerchantDetail(m)">查看详情</CButton>
          </view>
        </view>
        <text class="eat__link" @tap="goMerchants">查看附近全部商家 ›</text>
      </view>
    </CCard>

    <!-- 8. 专家问诊（§5.2-8；P1 权益，本期仅 UI） -->
    <CCard title="专家问诊" class="eat__card">
      <template v-if="expertUnlocked">
        <view class="expert">
          <image class="expert__icon" src="/static/icons/ic-gym.png" mode="aspectFit" />
          <view class="expert__main">
            <text class="expert__title">真人健身教练在线确认</text>
            <text class="expert__desc">进阶版 / 高级版可用</text>
          </view>
        </view>
        <CButton class="expert__btn" size="md" block @click="onConsult">立即咨询</CButton>
      </template>
      <CNoBenefit
        v-else
        text="专家问诊为进阶版 / 高级版权益"
        button-text="立即开通"
        @action="onConsult"
      >
        <view class="expert expert--dim">
          <image class="expert__icon" src="/static/icons/ic-gym.png" mode="aspectFit" />
          <view class="expert__main">
            <text class="expert__title">真人健身教练在线确认</text>
            <text class="expert__desc">进阶版 / 高级版可用</text>
          </view>
          <CButton class="expert__btn" size="md" block disabled>立即咨询</CButton>
        </view>
      </CNoBenefit>
    </CCard>
  </view>
</template>

<script setup lang="ts">
/**
 * FE3 · 吃什么（饭点决策）— Phase 2 (M2)
 * 依据：docs/split/03-页面布局与交互说明.md §5.2（原型图 + 8 条交互）
 *      docs/split/02-UI设计规范.md §4（设计令牌 / 组件复用）
 */
import { computed, onUnmounted, ref } from 'vue'
import { onLoad, onShow } from '@dcloudio/uni-app'
import { useAccountStore } from '@/stores/account'
import { useUserStore } from '@/stores/user'
import { useToast } from '@/composables/useToast'
import { useVoice } from '@/composables/useVoice'
import { useRecordCombo, COMBO_SPLIT } from '@/composables/useRecordCombo'
import { recommend } from '@/api/ai'
import { getMerchantCompare, getSkuCatalog } from '@/api/merchant'
import { track } from '@/utils/track'
import { BASE_URL, getToken } from '@/api/request'
import type { Envelope, GeoLocation, MerchantCompareItem, RecognizeData, RecommendOption } from '@/types/api'

/* ---------- 常量 ---------- */

const MEAL_LABEL: Record<number, string> = { 1: '早餐', 2: '午餐', 3: '晚餐', 4: '加餐' }

/** 健康等级（§5.2-4 绿/黄/红色条） */
type Level = 'good' | 'mid' | 'bad'
const LEVEL_TEXT: Record<Level, string> = { good: '推荐', mid: '可接受', bad: '建议少吃 / 替代' }

/**
 * 单餐热量阈值（kcal）。
 * 【假设】AiRecommendData/RecommendOption 契约未返回健康等级字段（仅 name/calories/reason），
 * 等级按「单餐绝对热量 + 占今日剩余额度比例」本地推算：
 *   ≥800 或 超今日剩余 → 红（bad）；≥600 或 占剩余 >60% → 黄（mid）；其余 → 绿（good）。
 * 后端补充 level 字段后改为直接读取即可。
 */
const MEAL_KCAL_HIGH = 800
const MEAL_KCAL_MID = 600
const LEFT_RATIO_MID = 0.6

/** 「AI 识别到」全局事件名，拍照页可通过 uni.$emit('eat:recognized', { foods: [...] }) 回传 */
const EVT_RECOGNIZED = 'eat:recognized'

/**
 * 标准减脂餐 SKU。
 * 【假设】src/api 暂无 sku/catalog 接口（契约与 Mock 有 /api/sku/catalog，但前端未封装），
 * 故用静态数据，Phase 3 接入后替换；calories 取区间中值用于写入记录。
 */
interface StandardMeal {
  name: string
  range: string
  price: number
  calories: number
}
const STANDARD_MEALS: StandardMeal[] = [
  { name: '高蛋白餐', range: '400-500kcal', price: 28, calories: 450 },
  { name: '均衡餐', range: '500-600kcal', price: 32, calories: 550 },
  { name: '低碳餐', range: '400-500kcal', price: 30, calories: 450 },
  { name: '素食餐', range: '450-550kcal', price: 26, calories: 500 },
]

/* ---------- 状态 ---------- */

const accountStore = useAccountStore()
const userStore = useUserStore()
const toast = useToast()
const { recordCombo } = useRecordCombo()

// 默认餐次按时段推断（与 pages/record/camera.vue 口径一致）
const hour = new Date().getHours()
const mealType = ref<1 | 2 | 3 | 4>(hour < 10 ? 1 : hour < 15 ? 2 : hour < 20 ? 3 : 4)
const mealText = computed(() => MEAL_LABEL[mealType.value] || '加餐')

/** AI 识别到的食物名 */
const recognized = ref<string[]>([])
/** 本页拍照识别中（识别结果区显示「识别中…」） */
const recognizing = ref(false)
/** AI 推荐方案 */
const options = ref<RecommendOption[]>([])
const recLoading = ref(false)
const recError = ref(false)
const pickingIndex = ref(-1)
const addingIndex = ref(-1)

/** 「今天还剩」：仅在今日账户可用时展示，接口不可用整块隐藏（降级不白屏） */
const showLeft = computed(() => !accountStore.error && !!accountStore.today)
const leftLoading = computed(() => accountStore.loading && !accountStore.today)
const leftValue = computed(() => (showLeft.value ? Math.round(accountStore.left) : 0))

/** 专家问诊权益：tier ≥1（进阶/高级/终身）解锁；本期仅 UI，不做真问诊 */
const expertUnlocked = computed(() => userStore.tier >= 1)

/* ---------- 语音输入（G4） ---------- */

/** 转写文本回填：拆成食物名并入「AI 识别到」列表（本页无文本输入框，回填到识别结果） */
const voice = useVoice({
  onResult: (text) => {
    const names = text
      .split(COMBO_SPLIT)
      .map((s) => s.trim())
      .filter(Boolean)
    if (!names.length) return
    recognized.value = Array.from(new Set([...recognized.value, ...names]))
    toast.success({ title: '已识别语音内容' })
    // 语音菜名同样驱动推荐（§5.2「菜单拍照识别+推荐」：items 即识别结果）
    void loadRecommend().then(scrollToRecommend)
  },
})

const voiceLabel = computed(() => {
  if (voice.transcribing.value) return '识别中…'
  return voice.recording.value ? '录音中…点击结束' : '语音输入'
})

/* ---------- 附近商家比价（G5） ---------- */

const cmpItems = ref<MerchantCompareItem[]>([])
const cmpLoading = ref(false)
const cmpError = ref(false)
/** 用于比价的标准 SKU 目录 id（取目录首项，页面内缓存） */
const cmpSkuId = ref(0)

function fmtDistance(meters: number): string {
  if (!meters || meters <= 0) return ''
  return meters < 1000 ? `${meters}m` : `${(meters / 1000).toFixed(1)}km`
}

/** 取定位（gcj02）；失败降级为不带坐标（后端按默认城市返回），不阻断比价 */
function getLocationSafe(): Promise<GeoLocation | null> {
  return new Promise((resolve) => {
    uni.getLocation({
      type: 'gcj02',
      success: (res) => resolve({ lat: res.latitude, lng: res.longitude }),
      fail: () => resolve(null),
    })
  })
}

/** 取比价用标准 SKU（目录首项）；目录为空返回 0 */
async function ensureCompareSku(): Promise<number> {
  if (cmpSkuId.value) return cmpSkuId.value
  const data = await getSkuCatalog()
  cmpSkuId.value = data?.items?.[0]?.id ?? 0
  return cmpSkuId.value
}

async function loadCompare() {
  cmpLoading.value = true
  cmpError.value = false
  try {
    const skuId = await ensureCompareSku()
    if (!skuId) {
      // 无标准套餐目录：空态提示，不算错误
      cmpItems.value = []
      return
    }
    const loc = await getLocationSafe()
    const data = await getMerchantCompare({
      sku_id: skuId,
      ...(loc ? { lat: loc.lat, lng: loc.lng } : {}),
    })
    cmpItems.value = data?.items ?? []
  } catch (e) {
    // request 已统一 toast；此处置错误态提供「重试」入口
    cmpError.value = true
    cmpItems.value = []
  } finally {
    cmpLoading.value = false
  }
}

/** 预约：带所选标准 SKU 进入下单确认页 */
function goBook(m: MerchantCompareItem) {
  const items = [{ sku_id: cmpSkuId.value, name: m.sku_name, price: m.price, qty: 1 }]
  const query = [
    `merchant_id=${m.merchant_id}`,
    `merchant_name=${encodeURIComponent(m.name)}`,
    `items=${encodeURIComponent(JSON.stringify(items))}`,
  ].join('&')
  uni.navigateTo({ url: `/pages/order/confirm?${query}` })
}

function goMerchantDetail(m: MerchantCompareItem) {
  uni.navigateTo({ url: `/pages/merchant/detail?id=${m.merchant_id}` })
}

function fmt(n: number): string {
  return Math.abs(Math.round(n))
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, ',')
}

function levelOf(opt: RecommendOption): Level {
  // 等级单一真源 = 后端写在 reason 前缀里的语义（额度口径是「min(今日剩余, 餐次默认)」，
  // 前端本地重算必然与后端打架——加餐默认额度 200 时尤其明显），无前缀才回退本地推算
  if (opt.reason.startsWith('[推荐]')) return 'good'
  if (opt.reason.startsWith('[可接受]')) return 'mid'
  if (opt.reason.startsWith('[建议少吃]')) return 'bad'
  const calories = opt.calories
  const left = leftValue.value
  if (calories >= MEAL_KCAL_HIGH) return 'bad'
  if (left > 0 && calories > left) return 'bad'
  if (calories >= MEAL_KCAL_MID) return 'mid'
  if (left > 0 && calories > left * LEFT_RATIO_MID) return 'mid'
  return 'good'
}

/** 展示用推荐语：去掉等级前缀（等级已由右侧标签 + 色条表达） */
function reasonBody(reason: string): string {
  return reason.replace(/^\[[^\]]+\]\s*/, '')
}

/* ---------- 数据加载 ---------- */

/** 识别/语音出新推荐后，把推荐卡滚进视野（否则新卡片在折叠线以下，用户以为没推荐） */
function scrollToRecommend() {
  uni.pageScrollTo({ selector: '#eat-recommend', duration: 300, fail: () => {} })
}

async function loadRecommend() {
  recLoading.value = true
  recError.value = false
  try {
    const data = await recommend({
      meal_type: mealType.value,
      // §5.2「菜单拍照识别+推荐」：带上拍照/语音回传的识别菜名，
      // 后端按名匹配食物库拼组合（未命中的忽略，全部未命中回退标准库）
      items: recognized.value.length ? recognized.value : undefined,
    })
    options.value = data?.options ?? []
  } catch (e) {
    // request 已统一 toast；此处置错误态提供「重试」入口
    recError.value = true
    options.value = []
  } finally {
    recLoading.value = false
  }
}

/* ---------- 写入饮食记录（公共逻辑抽到 composables/useRecordCombo.ts） ---------- */

async function pickOption(opt: RecommendOption, index: number) {
  pickingIndex.value = index
  try {
    const count = await recordCombo(opt.name, opt.calories, mealType.value, 4)
    if (!count) {
      toast.info({ title: '未匹配到食物，请在「首页·记录」手动录入' })
      return
    }
    toast.success({ title: '已记下来' })
    await accountStore.refresh()
  } catch (e) {
    // recordCombo/createMeal 失败：兜底提示，避免 unhandled rejection
    toast.error({ title: (e as Error).message || '记录失败，请重试' })
  } finally {
    pickingIndex.value = -1
  }
}

async function addStandard(meal: StandardMeal, index: number) {
  addingIndex.value = index
  try {
    const count = await recordCombo(meal.name, meal.calories, mealType.value, 4)
    if (!count) {
      toast.info({ title: '该套餐暂不在食物库，可手动录入' })
      return
    }
    toast.success({ title: '已加入今日摄入' })
    await accountStore.refresh()
  } catch (e) {
    // recordCombo/createMeal 失败：兜底提示，避免 unhandled rejection
    toast.error({ title: (e as Error).message || '记录失败，请重试' })
  } finally {
    addingIndex.value = -1
  }
}

/* ---------- 交互 ---------- */

/** 菜单识别 + AI 推荐独立页（§5.2-2/3/4）：拍菜单 → 识别 → 方案卡，与热量记录页分离 */
/* ---------- 本页拍照识别（§5.2-2/3）：拍菜单 → 识别菜名 → 驱动推荐卡 ---------- */

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
      void recognizeImage(path)
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

async function recognizeImage(path: string) {
  track('meal_photo', { meal_type: mealType.value })
  recognizing.value = true
  try {
    const data = await uploadRecognize(path)
    const foods = (data.items || [])
      .map((it) => it.name)
      .filter((n): n is string => !!n && !!n.trim())
      .map((n) => n.trim())
    if (!foods.length) {
      toast.info({ title: '没识别出来，换个角度再试试' })
      return
    }
    recognized.value = foods
    // §5.2「菜单拍照识别+推荐」：识别结果原地展示，推荐卡立即按菜单刷新并滚进视野
    await loadRecommend()
    scrollToRecommend()
  } catch (e) {
    toast.error({ title: (e as Error).message || '识别失败，换个角度或重试' })
  } finally {
    recognizing.value = false
  }
}

/** 语音输入（G4）：小程序录音+转写；H5 等环境由 useVoice 优雅降级提示手动输入 */
function onVoice() {
  voice.toggle()
}

/** 通知占位（二期接入消息中心） */
function onNotice() {
  toast.info({ title: '消息中心后续版本支持' })
}

/** 问教练：跳 AI 对话页（Phase 2 已交付） */
function onAskCoach() {
  uni.navigateTo({ url: '/pages/ai/chat' })
}

/** 查看全部标准餐占位（待接入 SKU 列表） */
function onMoreStandard() {
  toast.info({ title: '全部标准餐即将上线' })
}

/** 商家已从 Tab 降为普通页（§3.2），由吃什么页保留入口（§5.2-7） */
function goMerchants() {
  uni.navigateTo({ url: '/pages/merchant/merchant' })
}

/** 专家问诊（G1）：跳真人教练工单对话页 */
function onConsult() {
  uni.navigateTo({ url: '/pages/coach/chat' })
}

function clearRecognized() {
  recognized.value = []
}

/* ---------- 生命周期 ---------- */

/** 识别结果回传通道②：全局事件（通道①为路由参数 foods） */
function onRecognized(payload: unknown) {
  const foods = (payload as { foods?: string[] } | null)?.foods
  if (Array.isArray(foods) && foods.length) {
    recognized.value = foods.filter((f) => typeof f === 'string' && f.trim()).map((f) => f.trim())
    // §5.2「菜单拍照识别+推荐」：识别结果变化 → 推荐卡按拍的菜单刷新
    void loadRecommend()
  }
}

let firstShow = true

onLoad((options) => {
  // 通道①：路由参数 ?foods=清蒸鱼,炒青菜
  const foods = (options as { foods?: string } | undefined)?.foods
  if (foods) {
    recognized.value = decodeURIComponent(foods).split(',').map((f) => f.trim()).filter(Boolean)
  }
  uni.$on(EVT_RECOGNIZED, onRecognized)
  void loadRecommend()
  // 附近商家比价（G5）：标准套餐 SKU 比价
  void loadCompare()
  // 今日账户（/api/account/today）→ 今天还剩 X kcal
  void accountStore.refresh()
  if (!userStore.detail) void userStore.fetchMe()
})

onShow(() => {
  // 首屏 onLoad 已拉过一次，此处只处理「拍照 / 记录页返回」后的刷新
  if (firstShow) {
    firstShow = false
    return
  }
  void accountStore.refresh()
})

onUnmounted(() => {
  uni.$off(EVT_RECOGNIZED, onRecognized)
  voice.dispose()
})
</script>

<style lang="scss" scoped>
.eat {
  padding: $space-md;
  padding-bottom: calc(#{$space-xl} + env(safe-area-inset-bottom));

  // 2. AI 帮我找吃的（§4.7 输入框外观 + §5.2-2 大输入框内含两个按钮）
  &__entry {
    padding: $space-md;
    margin-bottom: $space-md;
    background: $card;
    border: 1rpx solid $disabled; // 比 $border 深一档：卡片边界更明显
    border-radius: $radius-lg;
    box-shadow: $shadow;
  }

  &__entry-label {
    display: block;
    margin-bottom: $space-sm;
    font-size: $t-28;
    font-weight: 500;
    color: $text-1;
  }

  &__entry-row {
    display: flex;
    gap: $space-sm;
  }

  &__entry-btn {
    flex: 1;
  }

  // 语音链路常驻提示（useVoice.notice）
  &__entry-notice {
    display: block;
    margin-top: $space-sm;
    font-size: $t-22;
    color: $warn;
  }

  // 3. 识别结果区
  &__recogn {
    padding: $space-lg;
    margin-bottom: $space-md;
    background: $card;
    border: 1rpx solid $disabled; // 比 $border 深一档：卡片边界更明显
    border-radius: $radius;
    box-shadow: $shadow;
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

  &__clear {
    display: block;
    margin-top: $space-sm;
    font-size: $t-22;
    color: $text-3;
    text-align: right;
  }

  // 4/6/7/8 通用卡片间距
  &__card {
    margin-bottom: $space-md;
  }

  // 5. 今天还剩 X kcal
  &__left {
    padding: $space-lg;
    margin-bottom: $space-md;
    background: $card;
    border: 1rpx solid $disabled; // 比 $border 深一档：卡片边界更明显
    border-radius: $radius;
    box-shadow: $shadow;
  }

  &__left-row {
    @include flex-center;

    margin-bottom: $space-md;
  }

  &__left-text {
    font-size: $t-26;
    color: $text-2;
  }

  &__left-num {
    margin: 0 $space-xs;
    font-size: $t-num-md;
    font-weight: 700;
    color: $brand;

    &--over {
      color: $danger;
    }
  }

  &__link {
    display: block;
    margin-top: $space-sm;
    font-size: $t-24;
    color: $brand;
    text-align: center;
  }
}

// AI 推荐方案卡（§5.2-4 左侧色条绿/黄/红）
.opts {
  display: flex;
  flex-direction: column;
  gap: $space-sm;
}

.opt {
  display: flex;
  overflow: hidden;
  background: $bg;
  border: 1rpx solid $disabled; // 比 $border 深一档：卡片边界更明显
  border-radius: $radius;

  // 左侧健康等级色条（§4.12：<60 红 / 60-80 黄 / >80 绿）
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

// 标准减脂餐 SKU 行（§5.2-6）
.sku {
  @include flex-between;

  padding: $space-sm 0;

  &:not(:last-of-type) {
    @include hairline(bottom);
  }

  &__main {
    flex: 1;
    min-width: 0;
  }

  &__name {
    display: block;
    font-size: $t-26;
    font-weight: 500;
    color: $text-1;
  }

  &__meta {
    font-size: $t-22;
    color: $text-2;
  }
}

// 附近商家比价卡片（§5.2-7，G5）
.cmp {
  display: flex;
  flex-direction: column;

  &__item {
    padding: $space-sm 0;

    &:not(:last-of-type) {
      @include hairline(bottom);
    }
  }

  &__head {
    @include flex-between;

    margin-bottom: $space-xs;
  }

  &__name {
    flex: 1;
    min-width: 0;
    font-size: $t-26;
    font-weight: 500;
    color: $text-1;
  }

  &__dist {
    margin-left: $space-sm;
    font-size: $t-22;
    color: $text-2;
  }

  &__meta {
    display: flex;
    align-items: center;
    margin-bottom: $space-xs;
  }

  &__star {
    width: 28rpx;
    height: 28rpx;
    margin-right: $space-xs;
  }

  &__rating {
    font-size: $t-22;
    color: $warn;
  }

  &__sku {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: $space-xs;
  }

  &__sku-name {
    font-size: $t-24;
    color: $text-1;
  }

  &__price {
    font-size: $t-26;
    font-weight: 700;
    color: $brand;
  }

  &__coupon {
    padding: 2rpx $space-xs;
    font-size: $t-22;
    color: $danger;
    background: rgba($danger, 0.1);
    border-radius: $radius-sm;
  }

  &__actions {
    display: flex;
    gap: $space-sm;
    margin-top: $space-sm;

    // 两个操作按钮等宽（CButton 为 view，flex 生效）
    :deep(.c-btn) {
      flex: 1;
    }
  }
}

// 专家问诊（§5.2-8）
.expert {
  @include flex-center;

  &__icon {
    width: 56rpx;
    height: 56rpx;
    margin-right: $space-sm;
  }

  &__main {
    flex: 1;
    min-width: 0;
  }

  &__title {
    display: block;
    font-size: $t-26;
    font-weight: 500;
    color: $text-1;
  }

  &__desc {
    font-size: $t-22;
    color: $text-2;
  }

  &__btn {
    margin-top: $space-md;
  }

  // 权益未开通时的灰显预览（CNoBenefit 内部再加灰度 + 蒙层）
  &--dim {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
