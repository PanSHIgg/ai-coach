// uni-app 约定：.vue 单文件组件类型声明（官方模板命名 shime-uni.d.ts）
/// <reference types="@dcloudio/types" />

declare module '*.vue' {
  import { DefineComponent } from 'vue'
  const component: DefineComponent<object, object, any>
  export default component
}
