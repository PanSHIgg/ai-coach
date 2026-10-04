<template>
  <view class="c-line" :style="{ height: `${height}rpx` }">
    <view class="c-line__plot">
      <template v-if="ready">
        <view
          v-for="(seg, i) in segments"
          :key="`seg-${i}`"
          class="c-line__seg"
          :style="seg.style"
        />
        <view
          v-for="(dot, i) in dots"
          :key="`dot-${i}`"
          class="c-line__dot"
          :class="{ 'c-line__dot--peak': dot.peak }"
          :style="dot.style"
        />
        <text v-if="peak" class="c-line__peak" :style="peakStyle">{{ peakText }}</text>
      </template>
    </view>
    <!-- 横轴刻度行常驻（高度固定）：保证首次量取的绘图区高度就是最终高度 -->
    <view class="c-line__axis">
      <text v-for="t in ticks" :key="t.key" class="c-line__tick" :style="t.style">
        {{ t.text }}
      </text>
    </view>
  </view>
</template>

<script setup lang="ts">
/**
 * CLineChart · 纯 view 折线图（不引图表库、不用 canvas，延续项目 view 拼图惯例）
 *
 * 实现：量取绘图区像素尺寸后，把每个点换算成 (x, y)；折线段用「旋转细条」连接
 * 相邻两点（width = 两点距离，transform: rotate = atan2 角度，origin 左端居中）。
 * 全部是标准 CSS，mp-weixin / H5 表现一致，无平台分支。
 *
 * 用法：
 * - points 按横轴顺序给点；value 为 null 表示该日无数据 → 断线不画点（绝不冒充 0）
 * - label 非空的点出横轴刻度（首/末刻度自动左/右对齐防出界）
 * - markPeak 标记最大值点（放大 + 白描边）并浮出数值标签
 */
import { computed, getCurrentInstance, nextTick, onMounted, ref, watch } from 'vue'
import type { CSSProperties } from 'vue'

interface Props {
  /** 横轴顺序点集；value=null = 无数据（断线） */
  points: { label?: string; value: number | null }[]
  /** 折线/圆点色（script 内取不到 SCSS 变量，由调用方传 tokens 对应色值） */
  color?: string
  /** 图表总高度（rpx，含横轴刻度行） */
  height?: number
  /** 归一下界（热量/步数类传 0；缺省取数据最小值，适用于体重这类区间图） */
  min?: number
  /** 标记最大值点并浮出数值标签 */
  markPeak?: boolean
  /** 峰值标签文案（缺省直接显示数值取整） */
  formatValue?: (v: number) => string
}

const props = withDefaults(defineProps<Props>(), {
  color: '#22c55e', // $brand
  height: 240,
  markPeak: false,
})

/* ---------- 常量 ---------- */
/** 折线粗细（px） */
const LINE_H = 3
/** 上下留白比例（markPeak 时头顶要多留数值标签的空间） */
const PAD_TOP_PLAIN = 0.1
const PAD_TOP_MARK = 0.28
const PAD_BOTTOM = 0.06
/** 数据跨度小于该值时把上界撑开，避免除零（与体重页 barRange 口径一致） */
const RANGE_EPS = 0.1

/* ---------- 绘图区量尺 ---------- */
const inst = getCurrentInstance()
const plotW = ref(0)
const plotH = ref(0)
const ready = computed(() => plotW.value > 0 && plotH.value > 0)

function measure() {
  nextTick(() => {
    if (!inst?.proxy) return
    uni
      .createSelectorQuery()
      .in(inst.proxy)
      .select('.c-line__plot')
      .boundingClientRect((rect) => {
        const r = rect as unknown as { width: number; height: number } | null
        if (r && r.width > 0 && r.height > 0) {
          plotW.value = r.width
          plotH.value = r.height
        }
      })
      .exec()
  })
}
onMounted(measure)
watch(
  () => [props.points, props.height],
  () => measure(),
)

/* ---------- 归一化与坐标 ---------- */
const range = computed(() => {
  const vals = props.points
    .map((p) => p.value)
    .filter((v): v is number => v !== null && v !== undefined && Number.isFinite(v))
  if (!vals.length) return { min: 0, max: 1 }
  const min = props.min ?? Math.min(...vals)
  let max = Math.max(...vals)
  if (max - min < RANGE_EPS) max = min + RANGE_EPS
  return { min, max }
})

function pos(index: number, value: number): { x: number; y: number } {
  const n = props.points.length || 1
  const x = ((index + 0.5) / n) * plotW.value
  const { min, max } = range.value
  const ratio = Math.min(1, Math.max(0, (value - min) / (max - min)))
  const padTop = plotH.value * (props.markPeak ? PAD_TOP_MARK : PAD_TOP_PLAIN)
  const padBottom = plotH.value * PAD_BOTTOM
  const y = plotH.value - padBottom - ratio * (plotH.value - padTop - padBottom)
  return { x, y }
}

/* ---------- 峰值 ---------- */
const peak = computed(() => {
  if (!props.markPeak) return null
  let bestIndex = -1
  let bestVal = -Infinity
  for (let i = 0; i < props.points.length; i += 1) {
    const v = props.points[i]?.value
    if (typeof v === 'number' && Number.isFinite(v) && v > bestVal) {
      bestVal = v
      bestIndex = i
    }
  }
  if (bestIndex < 0 || bestVal <= 0) return null
  return { index: bestIndex, value: bestVal }
})

const peakText = computed(() => {
  if (!peak.value) return ''
  const v = peak.value.value
  return props.formatValue ? props.formatValue(v) : String(Math.round(v))
})

const peakStyle = computed<CSSProperties>(() => {
  if (!peak.value || !ready.value) return {}
  const { x, y } = pos(peak.value.index, peak.value.value)
  // 峰值贴边时把标签横向钳回图内（轻微偏移，仍能对应到放大的峰值点）
  const labelX = Math.min(Math.max(x, 44), plotW.value - 44)
  return { left: `${labelX}px`, top: `${y - 12}px`, transform: 'translate(-50%, -100%)' }
})

/* ---------- 折线段（旋转细条） ---------- */
interface SegVm {
  style: CSSProperties
}
const segments = computed<SegVm[]>(() => {
  if (!ready.value) return []
  const out: SegVm[] = []
  for (let i = 0; i < props.points.length - 1; i += 1) {
    const a = props.points[i]
    const b = props.points[i + 1]
    if (!a || !b || a.value === null || b.value === null) continue
    if (!Number.isFinite(a.value) || !Number.isFinite(b.value)) continue
    const p1 = pos(i, a.value)
    const p2 = pos(i + 1, b.value)
    const dx = p2.x - p1.x
    const dy = p2.y - p1.y
    const len = Math.hypot(dx, dy)
    if (len < 1) continue
    const angle = (Math.atan2(dy, dx) * 180) / Math.PI
    out.push({
      style: {
        left: `${p1.x}px`,
        top: `${p1.y - LINE_H / 2}px`,
        width: `${len}px`,
        background: props.color,
        transform: `rotate(${angle.toFixed(2)}deg)`,
      },
    })
  }
  return out
})

/* ---------- 数据点 ---------- */
interface DotVm {
  style: CSSProperties
  peak: boolean
}
const dots = computed<DotVm[]>(() => {
  if (!ready.value) return []
  const out: DotVm[] = []
  props.points.forEach((p, i) => {
    if (p.value === null || !Number.isFinite(p.value)) return
    const { x, y } = pos(i, p.value)
    out.push({
      peak: peak.value?.index === i,
      style: {
        left: `${x}px`,
        top: `${y}px`,
        background: props.color,
        transform: 'translate(-50%, -50%)',
      },
    })
  })
  return out
})

/* ---------- 横轴刻度 ---------- */
interface TickVm {
  key: string
  text: string
  style: CSSProperties
}
const ticks = computed<TickVm[]>(() => {
  const n = props.points.length
  if (!n || !ready.value) return []
  const labeled = props.points.map((p, i) => (p.label ? i : -1)).filter((i) => i >= 0)
  if (!labeled.length) return []
  const first = labeled[0] ?? 0
  const last = labeled[labeled.length - 1] ?? 0
  return labeled.map((i) => {
    const x = ((i + 0.5) / n) * plotW.value
    // 首/末刻度改左/右对齐，避免 MM-DD 一半出图
    const align = i === first ? '0%' : i === last ? '-100%' : '-50%'
    const label = props.points[i]?.label ?? ''
    return {
      key: `${i}-${label}`,
      text: label,
      style: { left: `${x}px`, transform: `translateX(${align})` },
    }
  })
})
</script>

<style lang="scss" scoped>
.c-line {
  display: flex;
  flex-direction: column;
  width: 100%;

  &__plot {
    position: relative;
    flex: 1;

    // 基线
    &::after {
      content: '';
      position: absolute;
      right: 0;
      bottom: 0;
      left: 0;
      height: 2rpx;
      background: $border;
    }
  }

  &__seg {
    position: absolute;
    height: 3px;
    border-radius: 3px;
    transform-origin: 0 50%;
  }

  &__dot {
    position: absolute;
    box-sizing: border-box;
    width: 14rpx;
    height: 14rpx;
    border-radius: 50%;

    // 峰值点：放大 + 白描边，与普通点区分
    &--peak {
      width: 24rpx;
      height: 24rpx;
      border: 5rpx solid #fff;
      box-shadow: 0 2rpx 8rpx rgba(0, 0, 0, 0.2);
    }
  }

  &__peak {
    position: absolute;
    z-index: 2;
    padding: 2rpx 12rpx;
    font-size: $t-22;
    font-weight: 500;
    color: $text-1;
    white-space: nowrap;
    background: $bg;
    border-radius: 999rpx;
  }

  &__axis {
    position: relative;
    height: 32rpx;
    margin-top: 8rpx;
  }

  &__tick {
    position: absolute;
    top: 0;
    font-size: $t-22;
    color: $text-3;
    white-space: nowrap;
  }
}
</style>
