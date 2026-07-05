import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath } from 'node:url'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  test: {
    environment: 'happy-dom',
    globals: true,
    include: ['tests/**/*.{test,spec}.{js,mjs}'],
    // 不跑 .vite-cache 或 node_modules
    exclude: ['node_modules', 'dist'],
    // view-level 走 jsdom（happy-dom 不实现 getBoundingClientRect，el-table 列宽塌陷）
    // composables/stores/lib 保留 happy-dom（更快）
    environmentMatchGlobs: [
      ['tests/views/**', 'jsdom'],
      ['tests/components/**', 'jsdom'],
      ['tests/smoke/**', 'jsdom'],
    ],
  },
})