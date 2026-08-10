# spec-delta: frontend — initializing 推送丢弃门

## REQ-FE-532（新增）：系统初始化期间推送丢弃门（init-push-gate 2026-08-10）

前端 MUST 在「系统初始化中」（收到 `init_start`，尚未收到 `init_completed`/`init_aborted`）期间，丢弃写持仓状态的推送：

- `holdings.js` 新增 `initializing` ref（默认 false），供 ws_dispatch 读
- `ws_dispatch._onSystemStatusChange`：
  - `change_kind='init_start'` → `initializing=true` + 清零丢弃计数
  - `change_kind='init_aborted'` → `initializing=false` + 一次汇总日志（丢弃 N 条）
  - `change_kind='init_completed'` → `initializing=false` + 一次汇总日志 + 既有 resetForNewDay
- `_onPosPush` / `_onOrderCfm` / `_onTradeCfm` 顶部 gate：`initializing=true` 时直接丢弃（只计数，不逐条刷日志）
- **不 gate `quote`**（行情只更新价格显示，不写 positions/orders/trades）
- 兜底关门：`SystemInit.vue handleInit` finally 置 false；`holdings_bootstrap` bootstrap/refreshAll finally 置 false

#### Scenario: init_start 后洪峰推送全部丢弃

- **GIVEN** 后端广播 init_start (initializing=true)
- **WHEN** broker 推 pos_push 洪峰逐条到达
- **THEN** 每条 push MUST 被丢弃（positions/orders/trades 不写）
- **AND** MUST 只累计计数，不逐条刷日志

#### Scenario: init_completed 关闭门并汇总

- **WHEN** 后端广播 init_completed
- **THEN** `initializing` MUST 置 false
- **AND** 若期间丢弃 N 条，MUST 只打一条「初始化期间丢弃 N 条推送」日志
- **AND** 既有 resetForNewDay 照常执行（RPC 全量拉权威数据）

#### Scenario: init_aborted 关闭门不切日

- **WHEN** 后端广播 init_aborted
- **THEN** `initializing` MUST 置 false
- **AND** MUST 不触发 resetForNewDay（日未切，保持现状）

#### Scenario: 行情推送不受门影响

- **WHEN** initializing=true
- **THEN** `quote` 推送 MUST 照常写入（不 gate）

## Cross References

- `push/spec.md` REQ-PUSH-043（init_start/init_aborted 广播）
- `frontend/spec.md` REQ-FE-531（WS pos_push 新持仓批量合并）——洪峰日志已降噪，丢弃门进一步屏蔽中间态
