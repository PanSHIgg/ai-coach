import { defineConfig } from 'vite'
import uni from '@dcloudio/vite-plugin-uni'
import { fileURLToPath, URL } from 'node:url'

// P0-f：uni-app Vue3 工程 Vite 配置
// - @ 别名指向 src（tsconfig.json paths 同步配置）
// - uni 插件读取 src/pages.json、src/manifest.json
export default defineConfig({
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  plugins: [uni()],
})
