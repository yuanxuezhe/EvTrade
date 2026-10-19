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

## C6 — Pinia stores 动态 import — SKIPPED (2026-10-18 风险复评)

> 不实施 C6。原提案的"延迟到 ready==true 后调"风险:
> - watch(`auth.isAuthenticated`) 与 onMounted 都会触发 `holdingsStore.bootstrap()`,重复调用的去重保证薄弱,容易踩雷
> - 路由懒加载 view 已包住大部分 store 实际使用,主图减重收益小
> - 收益已被 C3 (fire-and-forget hydrate) 覆盖 — 首帧立即出 spinner
>
> C6 留给 Phase 2 后续,不阻塞本 change 出货.

## C7 — build 验证 (无 commit,已过)

- [x] `npm run build` 通过,主图 1326 KB / 431 KB gzip (与 P0 摸底持平,符合预期 — 不动 store import)
- [x] vite dev HMR 已 live,App.vue 不再 await hydrate 立即生效

## C8 — 归档 + push + 重启

- [ ] mv changes → archive (rename on git)
- [ ] AGENTS.md 追 ✅ 已归档行
- [ ] `git push origin master` (含 top-nav-overhaul merge commit + 5-6 new commits)
- [ ] 重启 4 服务 (frontend 拉新主图,但 vite dev HMR 已 live)
