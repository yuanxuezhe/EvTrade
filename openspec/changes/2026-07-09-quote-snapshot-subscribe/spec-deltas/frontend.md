# Spec Delta: frontend

## MODIFIED Requirements

### Requirement: quote store 订阅接口

`client/src/stores/quote.js` 新增方法 `subscribe(stock_codes: string[])` / `unsubscribe(stock_codes: string[])`。

#### Scenario: 订阅一组标的

- **WHEN** 调用 `quoteStore.subscribe(['600030.SH','000001.SZ'])`
- **THEN** 内部向 ws quote_update send: `{type:"subscribe", stock_codes:["600030.SH","000001.SZ"]}`
- **AND** 在 store 内 `pending_subscriptions` 集合加这些 code（避免重复发同订阅，幂等）
- **AND** 若 ws 未连接（重连中）→ 入队 onopen 后再发

#### Scenario: 收到 snapshot 帧

- **WHEN** 收到 ws 帧 `{type:"snapshot", stock_code:"600030.SH", data:{...}}`
- **THEN** 调 `quoteStore.update(data)` 与 v20 quote push 同路径
- **AND** `update()` 已存在，所以前端 UI（holdings / Trade quote panel）立即反映

#### Scenario: 收到 subscribe_ack

- **WHEN** 收到 `{type:"subscribe_ack", count:N, stock_codes:[...]}`
- **THEN** 从 `pending_subscriptions` 移除
- **AND** 不弹通知（低噪音）


### Requirement: Holdings.vue 订阅持仓

`client/src/views/Holdings.vue` 在 holdings 加载完毕后批量订阅所有持仓代码。

#### Scenario: 加载持仓后

- **WHEN** `holdings.listings` 加载完毕
- **THEN** 调 `quoteStore.subscribe(holdings.listings.map(h => h.stock_code))`

#### Scenario: 持仓代码列表变化

- **WHEN** 用户 buy/sell 后 holdings 变动
- **AND** 新增 stock_code 出现
- **THEN** 增量订阅新 code（diff with already subscribed），避免重复

### Requirement: Trade.vue OrderForm watch stock_code

`Trade.vue` 中 OrderForm 父组件传入 quickStock 后,OrderForm watch 自己的 form.stock_code。

#### Scenario: 输入新代码

- **WHEN** OrderForm form.stock_code 变化（用户输入或点击外部股票链接）
- **AND** 变化后稳定 300ms（debounce）
- **THEN** 调 `quoteStore.subscribe([newCode])`

#### Scenario: OrderForm mount

- **WHEN** OrderForm 默认 stock_code 有值（query param 传入）
- **THEN** mount 后立即 `subscribe([defaultCode])`，不等 input 事件

### MODIFIED Requirements

#### Requirement: ws_dispatch 分发

`client/src/stores/ws_dispatch.js:dispatchPayload(payload)` 增加 `snapshot` / `subscribe_ack` 分支。

#### Scenario: payload.type === "snapshot"

- **WHEN** `dispatchPayload({type:"snapshot", stock_code, data})`
- **THEN** 调 `_onQuote(data)`（已有路径）

#### Scenario: payload.type === "subscribe_ack"

- **WHEN** `dispatchPayload({type:"subscribe_ack", count, stock_codes})`
- **THEN** 从 quote store pending_subscriptions 移除已 ack 的 code
- **AND** 不发 ElNotification

#### Scenario: payload.type === "quote"（兼容老）

- **WHEN** `dispatchPayload({type:"quote", channel:"quote_update", data:row})`
- **THEN** 走 `_onQuote(row)`（v20 行为不变）
