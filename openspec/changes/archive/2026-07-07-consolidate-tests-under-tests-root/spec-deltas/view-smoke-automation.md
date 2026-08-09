# view-smoke-automation delta — consolidate-tests-under-tests-root（路径修订）

> change `2026-07-06-consolidate-tests-under-tests-root`
>
> smoke 测试**内容完全不变**，仅路径从 `client/tests/smoke/` 整体平移到 `tests/client/smoke/`，相关 npm script 路径同步更新。

## MODIFIED Requirements

### Requirement: stub-based 烟雾自动化（路径修订）

`tests/client/smoke/` MUST 覆盖 add-manual-adjust-and-history-pages 6.3/6.4 Defer 的全链路状态机（路径原 `client/tests/smoke/`）：
- `today-flow.test.js`（迁到 `tests/client/smoke/today-flow.test.js`）覆盖 login → holdings.bootstrap → IDB miss → HTTP fallback → admin adjustPosition / adjustAsset → admin reconcile → 调平被冲掉
- `history-query.test.js`（迁到 `tests/client/smoke/history-query.test.js`）覆盖路由 → 日期 chip → stockCode 过滤 → API getOrders / getTrades → 结果渲染
- smoke 测试 MUST vi.mock `src/stores/ws_heartbeat` 避免 bootstrap 后 _startWs 真连 ws 服务（Node undici WebSocket 抛 ERR_INVALID_ARG_TYPE）
- smoke 测试 MUST 在 `npm test -- --run` 默认包含，无需手动启 dev server / RPC / broker

### npm script 修订

`client/package.json` 的 `test` script：
- 旧：`"test": "vitest run"`
- 新：`"test": "vitest run --config ../tests/client/vitest.config.js"`

smoke 测试在 `cd client && npm test -- --run` 仍然被自动发现并跑（vitest 通过 `--config` 加载新位置配置，`include: ../tests/client/**/*.{test,spec}.{js,mjs}` 覆盖 smoke 子目录）。

## Scenarios

#### Scenario: smoke 测试 CI 可跑（路径修订）

- **WHEN** CI 跑 `cd client && npm test -- --run`
- **THEN** vitest 通过 `--config ../tests/client/vitest.config.js` 加载新配置
- **AND** smoke 测试 (`tests/client/smoke/today-flow.test.js` + `tests/client/smoke/history-query.test.js`) 与 unit 测试一起跑
- **AND** 总时间 < 60s
- **AND** 无需额外 step

#### Scenario: 完整 today-flow 链路（路径修订）

- **WHEN** 测试 `tests/client/smoke/today-flow.test.js` 执行：login admin → bootstrap → IDB mock miss → HTTP 拉数据 → adjustPosition +100 → adminReconcile
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

## 不在范围

- ❌ smoke 测试**业务逻辑**（assertion、mock 配置、test flow）的任何改动
- ❌ `add-manual-adjust-and-history-pages` 6.3/6.4 Defer 覆盖范围本身