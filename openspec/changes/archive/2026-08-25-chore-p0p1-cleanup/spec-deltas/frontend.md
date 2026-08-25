# frontend delta

## MODIFIED Requirements

### Requirement: Vitest 版本与依赖一致性

`client/package.json` SHALL pin `vitest@^1.6.0`（Vitest 实际主线版本，与 `@vue/test-utils@^2.x` / `happy-dom@^20.x` 配套）。The bogus `vitest@^4.1.9` pin (no such release exists, `npm install` fails) SHALL be replaced. The `jsdom` dev dependency SHALL be retained if used by `tests/client/vitest.config.js` `environmentMatchGlobs`; otherwise removed.

#### Scenario: npm install 成功

- **WHEN** developer runs `cd client && npm install`
- **THEN** installation succeeds without "no matching version found for vitest@^4.1.9" error

### Requirement: 死代码 / 死别名收敛

- `client/src/views/Dashboard.vue` SHALL NOT import `STATUS_TYPE` from `utils/format` (status rendering delegates to `<OrderStatusBadge>` component).
- `client/src/utils/format.js` SHALL NOT export `formatAmount = formatMoney` alias (single caller `T0Trade.vue:338` is inlined to `formatMoney`).
- `client/src/views/T0Trade.vue` SHALL call `formatMoney(...)` directly.

#### Scenario: format.js 导出收敛

- **WHEN** developer greps `client/src/` for `formatAmount`
- **THEN** 0 results (alias removed, caller inlined)

### Requirement: 不变项

- 任何 .vue 组件的 template / 业务逻辑 / store 接口零变更
- 表格列定义 / DataTableView 配置零变更
- 路由 / RBAC / WS 频道订阅零变更