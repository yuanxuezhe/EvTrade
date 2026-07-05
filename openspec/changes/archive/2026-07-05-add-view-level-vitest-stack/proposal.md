## Why

`add-manual-adjust-and-history-pages` 归档时留 3 个 Defer:
- **4.11** view-level 测试 (HistoryOrders / TodayOrders / TodayOrdersPanel 等) — 现有 vitest 仅覆盖 stores/api/composables 单测，view 组件零覆盖
- **6.3** 手动 UI today 流程 (login → /today/orders → IDB 恢复 → ws push → 调平 reconcile) — 需浏览器手点
- **6.4** 手动 UI history 查询 (/history/orders 日期区间选择) — 需 el-date-picker 交互

三者**互不阻塞但同根**：现有 vitest 栈只有 `@vitest-environment happy-dom` + 零 Element Plus 桩，无法 mount 真实 view。

需搭一套 view-level 测试基础设施 + 烟雾自动化:
1. jsdom 环境（比 happy-dom 更接近真实浏览器，el-table / el-pagination 内部依赖）
2. Element Plus 组件桩（只 stub 用到的子组件，避免完整 mock 重量级）
3. Vue Router / Pinia 测试桩
4. 视图组件挂载 helpers (`mountView` / `flushPromises`)
5. E2E 烟雾脚本（Playwright headless 或 stub-based 模拟点击流）

## What Changes

### 测试基础设施
- **NEW** `client/tests/setup-view.js`: jsdom env + Element Plus 桩 + vue-router 桩 + pinia 桩 + global `mountView` helper
- **NEW** `client/tests/views/_setup.js`: 视图测试公共 setup（mock quoteStore / holdingsStore / orderStore）
- **MODIFY** `client/vitest.config.js`: 新增 `environmentMatchGlobs` 让 `tests/views/**` 走 jsdom，其余保留 happy-dom

### 视图单测（解 4.11）
- **NEW** `client/tests/views/HistoryOrders.test.js`: mock api.getOrders, 验证日期区间 + stockCode 过滤
- **NEW** `client/tests/views/HistoryTrades.test.js`: 同上 for trades
- **NEW** `client/tests/views/Trade.test.js`: 验证 2 列 grid + panel 挂载 + onApplyPrice 传递
- **NEW** `client/tests/views/T0Trade.test.js`: smoke test 主表渲染 + 排序点击 + 快捷键 stub
- **NEW** `client/tests/components/trade/TodayOrdersPanel.test.js`: 验证 panel 委托渲染 + canCancel 守卫 + handleCancel 调用
- **NEW** `client/tests/components/trade/TodayTradesPanel.test.js`: 验证 panel 成交渲染 + 分页

### 烟雾自动化（解 6.3/6.4）
- **NEW** `client/tests/smoke/today-flow.test.js`: stub-based 模拟「login → 拉 holdings → IDB 恢复 → ws push 触发 applyOrderPush → 调平 PUT → reconcile 全表覆盖 → 调平消失」全链路
- **NEW** `client/tests/smoke/history-query.test.js`: stub-based 模拟「/history/orders → el-date-picker 选区间 → api.getOrders 区间 + 过滤 → 渲染响应」

### 依赖
- **NEW dev dep** `jsdom` (vitest 已有 happy-dom, 加 jsdom)
- 不引入 Playwright（stub-based 已覆盖关键路径，避免 e2e 重量级 + 网络/浏览器兼容）

## Capabilities

### New Capabilities
- `view-testing-stack`: vue view-level 测试栈（jsdom + Element Plus stub + mountView helpers）
- `view-smoke-automation`: 基于 stub 的烟雾自动化（替代手动 6.3/6.4）

### Modified Capabilities
（无 — 本 change 不改业务 spec，只补测试栈）

## Impact

**测试侧**:
- `client/vitest.config.js` 加 jsdom env 路由
- `client/tests/setup-view.js` 新文件
- `client/tests/views/**` + `client/tests/smoke/**` 新目录
- 预计新增 8-12 个测试文件，约 200-300 用例

**生产代码**:
- 零变更（不重构业务，只补测试）

**运行影响**:
- 测试栈变重（jsdom + Element Plus stub），单测时间 ~12s → ~25s
- CI 增量可接受（本地仍 < 30s）