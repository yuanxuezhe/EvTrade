# Tasks: frontend-initial-load-perf

## C1 — OpenSpec change 工件 (1 commit)

- [x] proposal.md
- [x] spec-deltas/frontend.md (REQ-FE-556 段)
- [x] tasks.md (本文件)

## C2 — spec merge (1 commit)

- [ ] `openspec/specs/frontend/spec.md` 加 `## REQ-FE-556` 段

## C3 — App.vue hydrate 非阻塞 (1 commit)

- [ ] `client/src/App.vue` 第 100-118 行: `await auth.hydrate()` → `auth.hydrate().catch(...)` 改 fire-and-forget
- [ ] `client/src/App.vue` 第 124-139 行 watch(isAuthenticated) 改 `await auth.ensureReady()` 替代顶层 await

## C4 — auth store ensureReady (1 commit)

- [ ] `client/src/stores/auth.js`: 新增 `ensureReady()` 函数:
  - 首次调用时启动 hydrate
  - 返回 shared promise (后续调用直接返已缓存 promise)
  - 失败 throw 不影响后续 (catch in caller)

## C5 — router guard await ensureReady (1 commit)

- [ ] `client/src/router/index.js`: `router.beforeEach` 顶部 `await auth.ensureReady()` 一次性等
- [ ] 已有的 `if (!auth.isAuthenticated)` 跳 /login 等判断保留 (在 ensureReady 之后)

## C6 — Pinia stores 动态 import (1 commit)

- [ ] `client/src/App.vue` setup 顶层 useXxxStore() 改按需:
  - `useUiStore / useAuthStore / useWsStore` → 仍顶层 (这些在 router/App.vue 生命周期早期要)
  - `useHoldingsStore / useStocksStore` → 改在 `authStore.ready===true` 后 (在 onMounted 块内)
  - `useAssetStore / useOrderStore / usePositionStore / useRpcStatusStore` → 路由进入对应 view 时按需 (本次不动 view,留给 Phase 2)

## C7 — build 验证 (无 commit)

- [ ] `npm run build` 通过
- [ ] 主图 chunk size 与 P0 摸底对比 (期望主图减 30-80 KB,因为 holdings/stocks store 动态化)

## C8 — 归档 + push + 重启

- [ ] mv changes → archive (rename on git)
- [ ] AGENTS.md 追 ✅ 已归档行
- [ ] `git push origin master` (含 top-nav-overhaul merge commit + 5-6 new commits)
- [ ] 重启 4 服务 (frontend 拉新主图,但 vite dev HMR 已 live)
