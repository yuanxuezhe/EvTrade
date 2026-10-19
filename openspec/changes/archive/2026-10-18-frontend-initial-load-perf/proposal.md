# frontend-initial-load-perf — 前端首屏加载性能优化 (2026-10-18)

## 解决什么

用户报告: 浏览器刷新或重新载入页面时**主图加载慢**，希望先把主要元素显示出来，其他慢慢加载。

**摸底 (P0, 2026-10-18)**:

| Chunk | 大小 / Gzip | 备注 |
|---|---|---|
| `index-*.js` | **1.33 MB / 431 KB** | 主图 (entry) |
| `install-*.js` | 569 KB / 192 KB | element-plus install |
| `ScriptTask-*.js` | 518 KB / 171 KB | CodeMirror |
| `ScriptDev-*.js` | 476 KB / 160 KB | CodeMirror |
| `TopNav-*.js` | 7.3 KB / 3.4 KB | 已分 chunk ✓ |
| 11 view (5-13 KB) | OK 路由 lazy ✓ | |

瓶颈:
1. **App.vue setup 顶层 `await auth.hydrate()`** — 必须等 IDB 读取 token 才能渲染 (P1 解决)
2. **Pinia 全 store 同步加载** — UI / auth / ws / holdings / stocks / asset / order / position / rpc_status 全部在 App.vue setup 顶层 `useXxxStore()` (P2 解决)
3. **主图 1.33 MB 整体阻塞首帧** — 现在不解决,等 P3 后续 (本次不拆 chunk)

## 阶段路线

### Phase 1 (本次实施, REQ-FE-556)

| 改动 | 文件 | 收益 |
|---|---|---|
| App.vue 不再顶层 await auth.hydrate();改 fire-and-forget | `client/src/App.vue` | 不等 IDB 读 token,首屏立刻绘制 (顶 nav + 启动屏障) |
| ~~Pinia stores 改动态 import~~ **(SKIPPED, 见下)** | `client/src/App.vue` | —— |
| Auth store 加 `ensureReady()` 共享 promise | `client/src/stores/auth.js` | router beforeEach 可 await 一次,后续实例直接返 |
| Router guard `await auth.ensureReady()` 第一次 | `client/src/router/index.js` | 路由判断与 hydrate 同步,但不阻塞首屏绘制 |
| ~~Pinia stores 延后到 ready==true 后调~~ **(SKIPPED)** | `client/src/App.vue` | watch(isAuthenticated) 重复触发风险,留给 Phase 2 |

> C6 SKIPPED 理由 (2026-10-18):
> - watch(`auth.isAuthenticated`) 与 onMounted 都触发 `holdingsStore.bootstrap()`,去重薄弱易踩雷
> - 路由 lazy view 已覆盖大部分 store 使用,主图减重收益小
> - C3 (fire-and-forget hydrate) 已覆盖首屏优化目标

### Phase 2 (后续, 不本次实施)

| 改动 | 文件 | 收益 |
|---|---|---|
| 主图 chunk 进一步拆: Pinia store 单独 chunk | `client/src/stores/*.js` | 主图 -200KB gzip,进入 / 后再拉 store chunk |
| ScriptDev / ScriptTask 单独 vendor | `client/vite.config.js` rollupOptions.output.manualChunks | 进 /script-* 才拉 CodeMirror |

## 风险

- ⚠️ App.vue 不 await 时,`authStore.ready` 在 hydrate 完成前 = false → 启动屏障 `v-if="!authStore.ready"` 仍显示,**未读 token 时首屏立刻显示屏障** ✅ (与原行为等价,只是不再 await)
- ⚠️ Pinia 动态 import 不能破坏现有模块语义 — useXxxStore() 在 setup 顶层调用时 store 还未 import 完成,**会抛 "no active Pinia"**。需要把 store import 时机延后到 `auth.ready === true` 后
- ⚠️ router beforeEach 已有 `if (!auth.isAuthenticated)` 跳 /login → ensureReady 后再判断。如果不 await,用户会被短暂弹跳登录页 (token 在 IDB 异步回读中)。**这是我们要解决的真正问题: 让 ensureReady 守门**

## 不做什么

- ❌ 不拆主图 chunk (留给 Phase 2)
- ❌ 不改 router 结构 / pageKey
- ❌ 不改 view 业务代码
- ❌ 不动后端 / hqserver / strategy_exec
- ❌ 不动 top-nav-overhaul 已合并到 master 的代码

## 实施顺序

| Step | 内容 | 类型 |
|---|---|---|
| 1 | 新增 change 工件 (本 proposal + tasks + spec-delta) | `docs(openspec)` |
| 2 | spec merge REQ-FE-556 | `docs(spec)` |
| 3 | App.vue setup 顶层 hydrate 不 await | `refactor(frontend)` |
| 4 | auth store 加 ensureReady | `refactor(frontend)` |
| 5 | router guard await ensureReady | `refactor(frontend)` |
| 6 | Pinia stores 部分动态 import | `refactor(frontend)` |
| 7 | build 验证 + 手动 chrome 实测 | 验证 |
| 8 | 归档 + push master + 重启 4 服务 | network |

## 知识库同步 (CLAUDE.md § 八)

- `openspec/specs/frontend/spec.md` 加 REQ-FE-556 段
- 不动 KB (业务文档本次无变化)
