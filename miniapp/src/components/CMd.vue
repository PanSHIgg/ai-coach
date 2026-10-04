<template>
  <mp-html
    class="md"
    :content="html"
    :container-style="containerStyle"
    :tag-style="tagStyle"
    scroll-table
    selectable
  />
</template>

<script setup lang="ts">
/**
 * CMd · Markdown 富文本渲染（AI 教练回复专用）
 *
 * 管线：markdown 文本 --markdown-it--> HTML --mp-html--> 小程序节点树。
 * mp-html 只渲染受信任的节点与属性并做安全过滤，适配小程序；表格
 * 开启横向滚动（scroll-table），文字长按可复制（selectable）。
 *
 * 【为什么是 markdown-it 而不是 marked】marked v18 的源码含 lookbehind
 * 探测（new RegExp("(?<=1)(?<!1)")）与命名捕获组正则字面量（(?<a>…)\k<a>），
 * 基础库 3.17.x 的正则包装器（@wechelpers/__wrap_reg_exp）处理这类正则会
 * 直接抛错，导致 vendor.js 模块注册失败、整个 appservice 瘫痪（白屏，
 * "Page has not been registered"）。markdown-it 面向老引擎设计，
 * 无 lookbehind / 命名组 / \p{}，对低端真机同样安全。
 */
import { computed } from 'vue'
import MarkdownIt from 'markdown-it'
import mpHtml from 'mp-html/dist/uni-app/components/mp-html/mp-html.vue'

const props = defineProps<{ content: string }>()

// html:false：AI 输出中的内嵌 HTML 一律转义展示（安全兜底）
// linkify：自动识别 URL；breaks：单个换行按 <br> 展示（聊天所见即所得）
const md = new MarkdownIt({ html: false, linkify: true, breaks: true })

const html = computed(() => md.render(props.content || ''))

/** 基础排版：与气泡正文一致（$t-26 / 1.6 / $text-1），颜色走 CSS 变量便于日后暗色适配 */
const containerStyle = 'font-size: 26rpx; line-height: 1.6; color: var(--text-1); word-break: break-word;'

/** 块级元素样式：间距对齐聊天气泡的紧凑排版；边框 / 底色用中性令牌 */
const tagStyle: Record<string, string> = {
  p: 'margin: 0 0 8rpx;',
  h1: 'font-size: 32rpx; font-weight: 600; margin: 12rpx 0 8rpx;',
  h2: 'font-size: 30rpx; font-weight: 600; margin: 12rpx 0 8rpx;',
  h3: 'font-size: 28rpx; font-weight: 500; margin: 12rpx 0 8rpx;',
  h4: 'font-size: 26rpx; font-weight: 500; margin: 8rpx 0;',
  ul: 'margin: 0 0 8rpx; padding-left: 36rpx;',
  ol: 'margin: 0 0 8rpx; padding-left: 36rpx;',
  li: 'margin: 4rpx 0;',
  blockquote: 'margin: 8rpx 0; padding: 8rpx 16rpx; border-left: 6rpx solid var(--border); color: var(--text-2);',
  code: 'font-size: 24rpx; padding: 2rpx 8rpx; background: var(--bg); border-radius: 8rpx;',
  pre: 'padding: 12rpx 16rpx; background: var(--bg); border-radius: 8rpx; overflow-x: auto;',
  table: 'border-collapse: collapse; margin: 8rpx 0;',
  th: 'border: 1rpx solid var(--border); padding: 8rpx 16rpx; background: var(--bg); font-weight: 500;',
  td: 'border: 1rpx solid var(--border); padding: 8rpx 16rpx;',
  a: 'color: var(--brand-dark);',
  hr: 'border: none; border-top: 1rpx solid var(--border); margin: 12rpx 0;',
}
</script>
