# tasks — element-plus-auto-import

## P0 — 验证 .vue 模板用图标组件名为 PascalCase 静态标签（无 dynamic :is）

- [ ] `grep -rE "el-icon[^>]*:is" client/src/` = 0 命中
- [ ] `grep -hroE "<[A-Z][a-zA-Z]+ ?/>" client/src/views/Trade.vue client/src/views/Dashboard.vue`
       看确为静态图标标签
- [ ] 确认 30+ 业务 .vue 模板里没出现 `<el-icon><component :is="...">` 这种动态名

## P1 — 装 unplugin-vue-components

- [ ] `cd client && uv add unplugin-vue-components`（按项目规范用 uv）
- [ ] 验证 `client/package.json` devDependencies 加了 `unplugin-vue-components`

## P2 — vite.config.js 改造

- [ ] 顶部加 `import Components from 'unplugin-vue-components/vite'`
- [ ] 顶部加 `import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'`
- [ ] plugins 数组 `vue()` 后追加 `Components({ resolvers: [ElementPlusResolver()] })`

## P3 — main.js 移除全量

- [ ] 删 `import ElementPlus from 'element-plus'`
- [ ] 删 `import * as ElementPlusIconsVue from '@element-plus/icons-vue'`
- [ ] 删 `// 注册所有 Element Plus 图标` 注释 + 整段 `for ([key,component] of Object.entries(...)) { app.component(...) }` 循环
- [ ] 删 `app.use(ElementPlus, { locale: zhCn })`
- [ ] 保留 `import zhCn from 'element-plus/dist/locale/zh-cn.mjs'`
- [ ] 保留 `import 'element-plus/dist/index.css'`
- [ ] 加 `app.config.globalProperties.$ELEMENT = { locale: zhCn }` 或在 #app 入口前 `ElementPlusLocale = zhCn` 兼容方案（避免 i18n 变英文）

## P4 — 验证

- [ ] `curl http://192.168.10.2:50998/src/main.js` 不再含 element-plus 全量 import / icons 全量循环
- [ ] `curl http://192.168.10.2:50998/src/views/Login.vue` 不再 import element-plus 全量 deps bundle
- [ ] `curl http://192.168.10.2:50998/src/views/Trade.vue` 同上
- [ ] 浏览器实测：登录 / Dashboard / Trade / T0 关键路径 el-* 正常 + 中文 i18n
- [ ] `cd client && npm run build` 编译通过（如果已有 build script）

## P5 — 知识库 + spec

- [ ] `knowledge/前端/build/按需引入.md` 或相关章节记录 unplugin-vue-components + ElementPlusResolver 用法
- [ ] spec/frontend/spec.md 追加 REQ-FE-551：element-plus 必须走 unplugin-vue-components 自动按需引入，禁止在 main.js 全量 import
- [ ] 归档 `mv openspec/changes/2026-09-23-element-plus-auto-import openspec/changes/archive/`
