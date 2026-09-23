# tasks — bundle-shrink-round-2

## P0 — 静态分析 + 拍板不优化范围

- [x] grep `from 'element-plus'` 命中 30 文件, 标出关键 layout 文件
- [x] App.vue setup 确认 ui/auth/ws/holdings/stocks 5 store 必须 eager
- [x] 决定 icons-vue bundle 不优化（复杂度 ROI 不划算），写入 proposal §"不做"
- [x] 决定 CSS 整包保留（已在 REQ-FE-551.4 拍板）

## P1 — App.vue 改 layout 异步组件

- [x] `import { defineAsyncComponent } from 'vue'` 加入 App.vue setup 顶部
- [x] Sidebar / AppHeader / OperationLog / BottomNav 4 个静态 import 改为 `defineAsyncComponent(() => import('...'))`
- [x] App.vue 内部使用方式不变 (template 里仍是 <Sidebar v-if=... />)

## P2 — 整包 import 改子路径

- [x] `views/Login.vue:119` — `from 'element-plus'` → `from 'element-plus/es'`
- [x] `components/AppHeader.vue:93` — `from 'element-plus'` → `from 'element-plus/es'`
- [x] `components/OperationLog.vue:105` — `from 'element-plus'` → `from 'element-plus/es'`

## P3 — 验证

- [x] `curl http://192.168.10.2:50998/src/views/Login.vue` 验证不含整包 import
- [x] `curl http://192.168.10.2:50998/src/components/AppHeader.vue` 验证不含整包 import + 无 disabled marker
- [x] `curl http://192.168.10.2:50998/src/components/OperationLog.vue` 同上
- [x] `curl http://192.168.10.2:50998/src/App.vue` 看 defineAsyncComponent
- [x] 手工验: 登录 / Dashboard / Trade / T0 / OperationLog 收发
- [x] `cd client && npm run build` 通过

## P4 — KB + spec

- [x] `知识库/前端/架构概览.md` 追加 layout lazy + 子路径 import 段落
- [x] `openspec/specs/frontend/spec.md` 追加 REQ-FE-552 段
- [x] 归档 change → archive/
- [x] commit "feat(frontend): 主图再瘦身 (REQ-FE-552)"
