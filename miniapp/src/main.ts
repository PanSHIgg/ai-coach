import { createSSRApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'

// 基础组件经 easycom 自动注册（pages.json custom 规则），无需全局注册
export function createApp() {
  const app = createSSRApp(App)
  app.use(createPinia())
  return { app }
}
