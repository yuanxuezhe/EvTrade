import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  cacheDir: '../.vite-cache',
  server: {
    port: 50998,
    host: '0.0.0.0',
    // 允许所有 Host 头（nginx 反代用 evtrade.ngx.evdata.top 访问）
    allowedHosts: true,
    // 禁用缓存：dev 模式 HMR 不可靠时, 强制浏览器重新请求
    headers: {
      'Cache-Control': 'no-store, no-cache, must-revalidate, proxy-revalidate',
      'Pragma': 'no-cache',
      'Expires': '0',
    },
    proxy: {
      // /api/agent/ws 已迁移至 /ws/agent_channel (2026-08-23, ai-agent-ws-reuse-channel)
      // 不再需要单独的 /api/agent/ws proxy — /api + /ws 已覆盖
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        ws: true,
      },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true
      }
    }
  }
})