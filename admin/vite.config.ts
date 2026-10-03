import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig({
  // 后台以 nginx 的 /admin/ 子路径提供服务（deploy/nginx.conf 的 ^~ /admin/ + alias），
  // 故 base 必须是 '/admin/'：产物 index.html 里的资源引用否则写成根路径 /assets/*，
  // 浏览器会绕过 /admin/ 前缀去请求，命中 nginx 404 → 白屏。
  base: '/admin/',
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5174,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
