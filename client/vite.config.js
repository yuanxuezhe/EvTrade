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
      // ⚠️ 必须先于 /api — vite 按顺序匹配，/api/agent/ws 需要单独走 WS proxy
      // （否则被下面 /api 的 HTTP proxy 接管，HTTP proxy 不转 WebSocket upgrade）
      '/api/agent/ws': {
        target: 'ws://localhost:8000',
        ws: true,
        changeOrigin: true,
      },
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        // 让 /api 也支持 WS（避免未来其他 WS 端点遗漏）
        ws: true,
      },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true
      }
    }
  }
})