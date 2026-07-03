## ADDED Requirements

### Requirement: REQ-PUSH-006 trd_cfm 触发 Position.vol 增量更新

broker 推 `trd_cfm` 时,后端在落库 Order / Trade 的同时 MUST 同步更新对应 stock_code 的 `Position.vol` 字段 (intra-day 实时性)。增量更新仅作用于 `vol` 字段;`cost_price` / `avl_vol` / `today_buy` / `today_sell` / `last_vol` 等由 day-init reconcile 兜底不动。

#### Scenario: 买单成交 → Position.vol 增加

- **WHEN** broker 推 trd_cfm,trade_type='23' (买),volume=100,stock_code='600030.SH'
- **AND** Position row 存在 (`stock_code='600030.SH'` 已由 day-init reconcile 创建)
- **THEN** `Position.vol` += 100
- **AND** `Position.cost_price` / `Position.avl_vol` / `Position.last_vol` 等其他字段不变

#### Scenario: 卖单成交 → Position.vol 减少

- **WHEN** broker 推 trd_cfm,trade_type='24' (卖),volume=50
- **AND** Position row 存在
- **THEN** `Position.vol` -= 50
- **AND** 其他字段不变

#### Scenario: Position 不存在 → log warning 跳过

- **WHEN** broker 推 trd_cfm 且对应 stock_code 的 Position row 不存在 (e.g. day-init reconcile 未跑)
- **THEN** `handle_trd_cfm` MUST log 一条 WARNING (含 order_no / trade_id / stock_code) 并跳过 Position.vol 更新
- **AND** Order / Trade 落库照常进行 (不阻塞成交写入)

#### Scenario: cancel-trade (trade_type=1) → 必须跳过 Position 更新

- **WHEN** broker 推 trade_type=1 (cancel-trade,user_def='CANCEL:orig_order_no') 的 trd_cfm
- **THEN** `handle_trd_cfm` MUST 跳过 Position.vol ±volume 逻辑 (按 OQ-1 选项 B 决议:DELETE 端点已抹平 `orig.cancelled_volume = orig.volume`,cancel-trade 是状态变更声明而非新增交易)
- **AND** `Position.vol` / `Position.cost_price` 等其他字段保持不变
- **AND** Order / Trade 落库照常进行 (cancel-trade 走与正常 trd_cfm 相同的 ORM 写入路径)

### Requirement: REQ-PUSH-007 pos_cfm / ast_cfm 删除 (BREAKING)

broker xtquant 协议不发送 `pos_cfm` 与 `ast_cfm` 推送事件 (xtquant 推送仅有 `ord_cfm` 与 `trd_cfm` 两个 func 名)。本 MUST 删除所有 `pos_cfm` / `ast_cfm` 路由、handler 文件、WS 频道与前端 store 入口;`pos_cfm` / `ast_cfm` MUST NOT 注册到任何 `_PUSH_CHANNEL` 或 `HANDLERS` dict 中。持仓 / 资金的实时性改由 `trd_cfm → Position.vol` 增量 (持仓层,REQ-PUSH-006) + day-init reconcile (权威快照) 共同满足。

#### Scenario: pos_cfm 不再有任何路由/handler/频道

- **WHEN** broker 意外推送 func='pos_cfm' 消息
- **THEN** push listener MUST log INFO 级别忽略 (do not route)
- **AND** `server/services/push/pos.py` 文件不存在
- **AND** `server/services/push/routes.py::_PUSH_CHANNEL` 中无 `pos_cfm` 键
- **AND** `server/services/push/handlers.py::HANDLERS` 中无 `pos_cfm` 入口
- **AND** WS 频道不存在 `position_update` 端点

#### Scenario: ast_cfm 不再有任何路由/handler/频道

- **WHEN** broker 意外推送 func='ast_cfm' 消息
- **THEN** push listener MUST log INFO 级别忽略
- **AND** `server/services/push/ast.py` 文件不存在
- **AND** `server/services/push/routes.py::_PUSH_CHANNEL` 中无 `ast_cfm` 键
- **AND** `server/services/push/handlers.py::HANDLERS` 中无 `ast_cfm` 入口
- **AND** WS 频道不存在 `asset_update` 端点

#### Scenario: 前端 store 移除 pos/ast push 入口

- **WHEN** 前端 store 模块加载
- **THEN** `client/src/stores/ws_dispatch.js` 中不存在 `_onPositionCfm` / `_onAssetCfm` 函数
- **AND** `dispatchPayload` switch 中不存在 `pos_cfm` / `ast_cfm` case
- **AND** `client/src/stores/holdings_push.js` 中不存在 `applyPositionPush` / `applyAssetPush` 函数
- **AND** `client/src/stores/holdings.js` 不 re-export 这些函数

### Requirement: REQ-PUSH-008 WS 频道列表 (变更后清单)

变更后 WebSocket MUST 仅推送 `order_update` (来自 ord_cfm) 与 `trade_update` (来自 trd_cfm) 两个频道。`position_update` / `asset_update` 频道 MUST NOT 注册到 `server/ws/manager.py`,**不再存在**。

#### Scenario: 前端依赖 position_update / asset_update 需迁移

- **WHEN** 前端代码或外部集成曾订阅 `position_update` 或 `asset_update` 频道
- **THEN** 该订阅将永远收不到消息 (服务端断流)
- **AND** **BREAKING**: 调用方必须迁移为轮询 `/api/holdings` (持仓) 与 `/api/asset` (资金)
- **AND** 持仓数量变化 → 通过 Order.status (broker 已报/已成交) 推 `order_update` 反查持仓是否变化
