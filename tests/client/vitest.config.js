import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath } from 'node:url'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('../../client/src', import.meta.url)),
    },
  },
  test: {
    environment: 'happy-dom',
    globals: true,
    include: ['../tests/client/**/*.{test,spec}.{js,mjs}'],
    exclude: ['node_modules', 'dist'],
    environmentMatchGlobs: [
      ['../tests/client/views/**', 'jsdom'],
      ['../tests/client/components/**', 'jsdom'],
      ['../tests/client/smoke/**', 'jsdom'],
    ],
  },
})
