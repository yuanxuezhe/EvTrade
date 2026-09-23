import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
// REQ-FE-551: element-plus + icons-vue 必须按需引入 — vite dev transform 时
//   扫描 .vue 里的 <el-button> / <Edit /> 静态标签自动注入 import & register,
//   取代 main.js 全量 import + 280+ 图标组件全量注册循环.
//   动态 <component :is="dynName"> 不在 resolver 扫描范围, 见 .vue 模板约束.
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

export default defineConfig({
  plugins: [
    vue(),
    // REQ-FE-551.5: 必须配 ElementPlusResolver 才能按需引入组件 + 图标
    Components({
      resolvers: [
        ElementPlusResolver({
          // REQ-FE-551.3: locale 由 resolver 在 transform 时按 el-* 用到的组件
          //   自动插入 `element-plus/es/locale/lang/<locale>/<comp>.mjs`,
          //   取代 main.js 整段 `import zhCn from '.../locale/zh-cn.mjs'`
          //   + `app.use(ElementPlus, { locale: zhCn })` (后者会引回全量 entry)
          locale: 'zh-cn',
          // REQ-FE-551.4: 暂时 css 整包, 不开 css 按需避免引入 .scss 编译复杂度
          importStyle: 'css',
          directives: true,
        }),
      ],
      // 仅扫描 .vue 模板 — 本项目 element-plus 仅在 .vue 用, 无 tsx/jsx
      include: [/\.vue$/],
    }),
  ],
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