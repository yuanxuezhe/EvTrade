# element-plus-auto-import（按需引入 element-plus 组件 + 图标）— 2026-09-23

## 解决什么

`client/src/main.js` 当前是 element-plus **全量**引入 + 280+ ElementPlus 图标组件**全量**注册：

```js
import ElementPlus from 'element-plus'                          // ~1.2 MB esbuild deps bundle
import * as ElementPlusIconsVue from '@element-plus/icons-vue'  // 全量 280+ 图标 ESM bundle
// ...
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)  // 全量挂到 app，el-icon 用图标组件名查找
}
```

**实测**（curl + waterfall 顺序拉取 50998，热态且 deps 已 cached）：
- `element-plus.js` 单请求 **665ms / 1.2 MB**（其他 deps 12-22ms，App.vue / router 1-2ms）
- 串行合计 ≈ 800ms，并发后首屏 DOMContentLoaded 仍受其拖累
- 冷态（首次 vite transform）再叠加 esbuild 预构建 element-plus deps → 5-15s

而**实际只用到 30+ 个 el-* 组件 + ~50 个 el-icon**（grep `<el-…>` 已确认），
30+ 个组件对应 element-plus 全部 100+ 组件不到一半，1.2 MB 大头明显浪费。

## 改动

1. **装两个 unplugin**
   - `unplugin-vue-components` — 扫 .vue 模板 `<el-button>` / `<el-icon><Edit /></el-icon>`，
     自动注入 `import { ElButton } from 'element-plus'` 与 `app.use(ElButton)` 替代物
   - `unplugin-auto-import` — 顺便自动 import Vue ref / computed / watch 等（不强制启用）
   - 配置走 **resolver：ElementPlusResolver** — 支持组件按需 + 图标按需

2. **vite.config.js 改造**
   ```js
   import Components from 'unplugin-vue-components/vite'
   import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'
   // …
   plugins: [
     vue(),
     Components({ resolvers: [ElementPlusResolver()] }),  // 自动按需
   ]
   ```

3. **main.js 改造**
   - 删 `import ElementPlus from 'element-plus'`
   - 删 `import * as ElementPlusIconsVue from '@element-plus/icons-vue'` 全量
   - 删 `for ([key,component] of Object.entries(ElementPlusIconsVue)) app.component(key, component)`
     全量循环（**关键**：图标现在按 resolver 按需注入 `<Edit />` 用到的那个）
   - 删 `app.use(ElementPlus, { locale: zhCn })` —— ElementPlusResolver 会按需注册
   - **保留**：`import zhCn from 'element-plus/dist/locale/zh-cn.mjs'`（locale 不在 resolver 范围，
     需要时一次性手动注入；可以走 `app.config.globalProperties.$ELEMENT = { locale: zhCn }` 或
     i18n config，且 ElementPlusResolver 不接管 locale）
   - **保留**：`import 'element-plus/dist/index.css'`（CSS 还是全量 v2.7，按需未分割；
     ElementPlus 自动 CSS 按需用 resolver 的 `importStyle: 'css'` 选项，css chunk 切片，
     但为不引入复杂度先沿用全量 CSS，1 个 CSS 文件 ≈ 200KB gzip < 1.2MB JS 收益）

4. **业务文件零改动**
   - 30+ .vue 模板里 `<el-button @click>` / `<el-icon><Edit /></el-icon>` 全部**保持原样**
   - resolver 自动按需注入对应用到的组件 import + import 语句 + 局部注册

## 影响面

- **main.js**：移除 4 行 + 整段图标注册循环
- **vite.config.js**：加 1 plugin
- **业务 .vue**：不需改任何模板（最理想情况）
- **唯一新增 dep**：`unplugin-vue-components`（仅 devDependency，
  影响构建 / vite dev 运行，**不影响 prod 产物逻辑**）
- **风险点**：
  - Resolver 偶尔识别不出非标准大小写（`<Edit />` 配 `edit` 注册）—— 已知模板都是 `<Edit />` PascalCase 无此风险
  - 图标按 `<component :is="SomeIcon">` 动态传名 → resolver **不会自动识别**。需先 grep 确认本项目无此用法
  - `app.use(ElementPlus, { locale: zhCn })` 移除后，ElementPlus 组件内部 i18n 会变英文 → 必须保留 locale 注入方案

## 验证

1. `curl http://192.168.10.2:50998/src/main.js` 看返回体**不再**有
   `import ElementPlus from …` 与全量 icons 全局循环
2. `curl http://192.168.10.2:50998/src/views/Login.vue` 看响应**不再**依赖 element-plus 全量 deps bundle
3. 浏览器手测：登录页 / Trade / Dashboard / T0 等关键路径 el-* 都正常渲染 + 中文 i18n
4. `npm run build` 编译通过（vite build 不动 main.js 源但需 plugin 兼容）
