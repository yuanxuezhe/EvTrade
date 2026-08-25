# 2026-08-25-t0-quote-subscription — Tasks

## Step 0: 知识库 + spec

- [x] git pull origin master（CLAUDE.md § 一）
- [x] 检索 `client/src/views/StkPoolView.vue` 教科书订阅模式（L140-241）
- [x] 检索 `client/src/stores/quote.js` subscribe/unsubscribe 契约（L171-198）
- [x] 检索现有 REQ-FE-NNN 编号（最大 537 → 本次 538）
- [x] 创建 change 目录 + proposal.md

## Step 1: 创建 change

- [x] `openspec/changes/2026-08-25-t0-quote-subscription/proposal.md`
- [x] `openspec/changes/2026-08-25-t0-quote-subscription/tasks.md` (本文件)
- [ ] `openspec/changes/2026-08-25-t0-quote-subscription/spec-deltas/frontend.md`

## Step 2: 实施（按 v6 commit 拆 commit）

### Commit 1: composable 新建

- [ ] 新建 `client/src/composables/useQuoteSubscription.js`（~50 行）
  - `useQuoteSubscription(codesGetter)` 返回 `{ codes }`
  - watch codes (immediate + flush:post) → diff 旧/新 → subscribe/unsubscribe
  - onBeforeUnmount → unsubscribe(current)
  - 去重 + 过滤 falsy
- [ ] 跑 `python -c "import ast; ast.parse(open('client/src/composables/useQuoteSubscription.js').read())"` 验语法

### Commit 2: T0Trade.vue 接入（修主问题）

- [ ] `client/src/views/T0Trade.vue` 加 `import { useQuoteSubscription } from '../composables/useQuoteSubscription'`
- [ ] 在 setup 末尾加 `useQuoteSubscription(() => taskRows.value.map(r => r.stock_code).filter(Boolean))`
- [ ] 不删现有 `quoteStore` import（其他场景可能用到）
- [ ] 验脚本：`grep -n 'quoteStore.subscribe' client/src/views/T0Trade.vue` 仍为空（保持极简）

### Commit 3: StkPoolView 重构（行为不变）

- [ ] `client/src/views/StkPoolView.vue`:
  - L149-150 删 `detailCodes` computed（composable 内部 computed 等价）
  - L180-187 `onBeforeUnmount` 块简化（只留 unmounted flag guard，unsubscribe 由 composable 自动）
  - L216-220 `loadDetail` 内 `quoteStore.subscribe(codes)` 删
  - L230-241 `switchPool` 内 unsubscribe/subscribe 删
  - 加 `useQuoteSubscription(() => detail.value.map((d) => d.stock_code))`

**注**: QuotePanel.vue 不在 v1 范围（debounce + 清空保留订阅行为不兼容）

### Commit 4: spec delta

- [ ] `openspec/changes/2026-08-25-t0-quote-subscription/spec-deltas/frontend.md` 写 REQ-FE-538
- [ ] 合并到 `openspec/specs/frontend/spec.md` REQ-FE-538 段（保留原始章节编号顺序）

## Step 3: 验证

- [ ] `cd client && npm run build` 通过
- [ ] `cd client && npm test` 验证 useQuoteSubscription.test.js 全过
  - **注意**: 项目 vitest 基础设施有历史 bug (`vitest@4.1.9` 不导出 `vitest/config` 子路径, 但 `tests/client/vitest.config.js` 引用了). 已在 stash 状态下复现 useQuickT0 也有同样问题. 本次 change 不修基础设施 bug, 仅写测试 + 标记
- [ ] `pytest hq/ server/tests/` 基线不掉（CLAUDE.md § 八：71 collected / 64 passed 不掉）
- [ ] 手动验证 T0Trade 页面订阅生效（DevTools ws 帧）
- [ ] 手动验证切换 task 订阅 diff 生效
- [ ] 手动验证离开页面无幽灵订阅
- [ ] StkPoolView 切换池 + 进入退出页面回归

## Step 4: 归档

- [ ] `git diff --stat` 自查（4 个 commit 各 < 50 行）
- [ ] commit 顺序：composable 1 + T0Trade 1 + StkPool/QuotePanel 1 + spec 1
- [ ] `mv openspec/changes/2026-08-25-t0-quote-subscription openspec/changes/archive/`
- [ ] 更新 `openspec/AGENTS.md` 当前活跃 change 列表
