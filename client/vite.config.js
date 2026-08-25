import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  cacheDir: '../.vite-cache',
  optimizeDeps: {
    // 关闭 dep 预打包 sourcemap, 避开 Windows 上 esbuild 写 .map 文件的
    // "Access is denied" 锁文件问题 (element-plus 大依赖图首次加载时偶发)。
    // dev 模式 sourcemap 对调试作用有限, 关掉显著降低冷启动风险。
    esbuildOptions: { sourcemap: false },
  },
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