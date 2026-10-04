/**
 * 第三方组件环境声明（mp-html 集成）。
 *
 * `mp-html/dist/uni-app` 的组件未随包提供类型声明，这里给出聊天内
 * Markdown 渲染所需的最小 props 声明；有了该声明后 vue-tsc 不再解析
 * 其 JS 源码（ambient module 优先于文件解析），build 时仍由 vite
 * 按真实路径打包。
 */
declare module 'mp-html/dist/uni-app/components/mp-html/mp-html.vue' {
  import type { DefineComponent } from 'vue'

  const MpHtml: DefineComponent<
    {
      /** 用于渲染的 html 字符串（由 marked 转换得到） */
      content?: string
      /** 容器样式（inline style 字符串，支持 rpx / CSS 变量） */
      containerStyle?: string
      /** 标签默认样式：键为标签名，值为 inline style 字符串 */
      tagStyle?: Record<string, string>
      /** 给表格加横向滚动层 */
      scrollTable?: boolean | string
      /** 长按可复制 */
      selectable?: boolean | string
    },
    Record<string, never>,
    unknown
  >
  export default MpHtml
}
