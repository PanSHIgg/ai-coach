import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

// 前端单测基座（与 vite.config.ts 的 @ -> src 别名保持一致）。
// 不复用 @dcloudio/vite-plugin-uni：单测不编译小程序/H5 产物，只做 Node/jsdom 下
// 的模块与组件行为验证，统一 mock uni 全局 API。
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  test: {
    environment: 'jsdom',
    include: ['tests/**/*.spec.ts'],
    setupFiles: ['./tests/setup.ts'],
    // 样式不参与单测（SFC <style> 会被替换为空模块，避免依赖 uni.scss 变量注入）
    css: false,
  },
})