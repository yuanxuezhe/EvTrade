# Tasks — add-view-level-vitest-stack

按 scope 拆 6 commit, 单 change。顺序按依赖（env 路由 → setup → view tests → smoke → docs sync → archive）。

## 1. vitest.config.js jsdom env 路由 (commit: chore(client))

- [x] 1.1 `client/vitest.config.js` 加 `environmentMatchGlobs`: `tests/views/**` + `tests/components/**` + `tests/smoke/**` 走 jsdom；其余保留 happy-dom
- [x] 1.2 验证: `npm test -- --run` 175 旧用例仍全过（happy-dom 路径不变）

## 2. setup-view.js 基础设施 (commit: test(client): view 测试基础设施)

- [x] 2.1 新建 `client/tests/setup-view.js` (~280 行): vi.mock('element-plus/icons-vue') + vi.mock('element-plus', ElPlusStub 17 组件) + vi.mock('vue-router', RouterStub) + beforeEach setActivePinia + global.mountView + global.flushPromises
- [x] 2.2 新建 `client/tests/views/_setup.js` (~50 行): makeOrder / makeTrade mock 数据 helpers
- [x] 2.3 验证: 单文件 `mountView(HistoryOrders)` 不报错

## 3. view 单测 (commit: test(client): HistoryOrders + HistoryTrades + Trade view 单测)

- [x] 3.1 新建 `client/tests/views/HistoryOrders.test.js` (11 用例): mount + chip 切换 + picker 校验 + stockCode 过滤 + 422 + 渲染 + 导出
- [x] 3.2 新建 `client/tests/views/HistoryTrades.test.js` (8 用例): 同上 for trades
- [x] 3.3 新建 `client/tests/views/Trade.test.js` (5 用例): 2 列 grid + panel 挂载 + onApplyPrice 传递

## 4. panel 单测 (commit: test(client): TodayOrdersPanel + TodayTradesPanel 单测)

- [x] 4.1 新建 `client/tests/components/trade/TodayOrdersPanel.test.js` (11 用例): 委托渲染 + canCancel 守卫 (终态 / cancel-row) + handleCancel 调 store + 分页
- [x] 4.2 新建 `client/tests/components/trade/TodayTradesPanel.test.js` (6 用例): 成交渲染 + 分页 + trade_type=1 撤单过滤

## 5. T0Trade 单测 (commit: test(client): T0Trade view 单测)

- [x] 5.1 新建 `client/tests/views/T0Trade.test.js` (19 用例): 主表渲染 + onSortChange + buyState/sellState/balanceState 守卫 + netExposure + getBalanceLabel + cumHistory

## 6. smoke 自动化 (commit: test(client): smoke 自动化替代 6.3/6.4)

- [x] 6.1 新建 `client/tests/smoke/_setup.js` (~25 行): mockIDB / mockWsPush / resetAllStores 公共 helpers
- [x] 6.2 新建 `client/tests/smoke/today-flow.test.js` (5 用例): login → bootstrap → IDB miss → HTTP fallback → adjustAsset / adjustPosition → reconcile 覆盖全链路
- [x] 6.3 新建 `client/tests/smoke/history-query.test.js` (10 用例): HistoryOrders + HistoryTrades chip / stockCode / 结果渲染 / 日期校验

## 7. 全量验证 (commit: chore(client))

- [x] 7.1 `npm test -- --run` → 250 全过 (175 旧 + 75 新 view/panel/smoke)
- [x] 7.2 单测时间 < 30s (实测 ~23s)
- [x] 7.3 `grep -r 'happy-dom' client/tests/{views,components,smoke}` → 0 行（确认 env 切换正确）
- [x] 7.4 `grep -r 'jsdom' client/tests/{composables,stores,lib}` → 0（确认旧栈未污染）

## 8. spec 同步 + 归档 (commit: docs(openspec))

- [x] 8.1 同步 specs: archive 工具自动 create 新 capability `openspec/specs/view-testing-stack/spec.md` (5 Scenario) + `openspec/specs/view-smoke-automation/spec.md` (5 Scenario)
- [x] 8.2 archive: `openspec archive add-view-level-vitest-stack` → `openspec/changes/archive/2026-07-05-add-view-level-vitest-stack/`

## 实施偏差备注

- task 1.1 env 路由范围扩到 `tests/smoke/**`（spec 原计划只 views + components, 但 smoke 也用 Pinia/store 需 jsdom）
- task 5.1 实测 19 用例 (spec 估 ~40, 因 T0Trade 渲染重, 优先覆盖 store 交互逻辑: sort/buy/sell/balance/netExposure/cumHistory, drawer + keybindings 用 store 直接测)
- task 7.1 实测 250 全过 (spec 估 375+, 75 新测试覆盖核心 view/panel/smoke 路径)
- task 6.1 `mockWsPush` helpers 已建, 但 today-flow.test.js 实际改用直接 vi.mock('../../src/stores/ws_heartbeat') 避免 _startWs 真连 ws
- task 6.3 实测 10 用例 (Orders 7 + Trades 3, spec 估 ~10 一致)