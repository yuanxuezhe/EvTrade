# view-smoke-automation Specification

## Purpose

`client/tests/smoke/` 下的端到端业务状态机测试（change `add-manual-adjust-and-history-pages` 6.3/6.4 节 + change `add-view-level-vitest-stack`）。

- 覆盖：login → holdings.bootstrap → IDB miss → HTTP fallback → admin adjustPosition / adjustAsset → admin reconcile（调平被冲掉）
- 与 `view-testing-stack` 协作：本 spec 跑端到端链路，view-testing-stack 提供"挂载 + 断言"原语
- 通过 `vi.mock('src/stores/ws_heartbeat')` 避免 bootstrap 后 _startWs 真连 ws 服务（Node undici WebSocket 抛 ERR_INVALID_ARG_TYPE）

> **与 view-testing-stack 的边界**：
> - **本 spec（view-smoke-automation）**：跨 view + 多 store + mock IDB 的端到端链路测试；模拟"用户完整操作流程"
> - **兄弟 spec（view-testing-stack）**：单 view / 单 component 级别测试；挂载 → 操作 props/slots → 断言渲染结果 + store state

## Requirements
### Requirement: stub-based 烟雾自动化

`client/tests/smoke/` MUST 覆盖 add-manual-adjust-and-history-pages 6.3/6.4 Defer 的全链路状态机：
- `today-flow.test.js` 覆盖 login → holdings.bootstrap → IDB miss → HTTP fallback → admin adjustPosition / adjustAsset → admin reconcile → 调平被冲掉
- `history-query.test.js` 覆盖路由 → 日期 chip → stockCode 过滤 → API getOrders / getTrades → 结果渲染
- smoke 测试 MUST vi.mock `src/stores/ws_heartbeat` 避免 bootstrap 后 _startWs 真连 ws 服务（Node undici WebSocket 抛 ERR_INVALID_ARG_TYPE）
- smoke 测试 MUST 在 `npm test -- --run` 默认包含，无需手动启 dev server / RPC / broker

#### Scenario: 完整 today-flow 链路

- **WHEN** 测试执行：login admin → bootstrap → IDB mock miss → HTTP 拉数据 → adjustPosition +100 → adminReconcile
- **THEN** 最终 holdingsStore.positions[0].vol = 1100（调增 +100）
- **AND** 再调 adminReconcile 后 positions[0].vol = 1000（broker 真实值覆盖调平）
- **AND** synced_from = 'rpc_full'

#### Scenario: IDB miss 时降级 HTTP

- **WHEN** 测试 mock IDB loadOrdersForDate 返回空
- **THEN** bootstrap 走 HTTP api.getOrders
- **AND** 拉到的 2 笔订单写入 IDB（fire-and-forget）

#### Scenario: history chip + stockCode 过滤

- **WHEN** 测试触发 setPreset(PRESETS[1]) 最近三天 + stockCode='600030.SH'
- **THEN** api.getOrders 被调，参数含 startDate + endDate + stockCode='600030.SH'
- **AND** results.length = 响应 list 长度

#### Scenario: 422 日期区间校验

- **WHEN** 测试传 startDate > endDate
- **THEN** api.getOrders 不被调
- **AND** UI 显示「开始日期不能晚于结束日期」错误

#### Scenario: smoke 测试 CI 可跑

- **WHEN** CI 跑 `cd client && npm test -- --run`
- **THEN** smoke 测试与 unit 测试一起跑，无需额外 step
- **AND** 总时间 < 60s

