## ADDED Requirements

### Requirement: 策略事件 WS 频道 strategy_update（REQ-PUSH-007）

后端 MUST 新增 WS 频道 `strategy_update`，用于广播策略引擎触发事件。前端通过 `client/src/stores/ws.js` 订阅此频道。

现有 5 个频道（`order_update` / `trade_update` / `position_update` / `asset_update` / `quote_update`）不变。新频道解耦于其它频道，避免策略事件污染既有 5 频道。

#### Scenario: 频道注册

- **WHEN** 后端启动
- **THEN** `server/ws/endpoint.py` MUST 注册 `strategy_update` 频道到 ws_manager

#### Scenario: payload schema

策略事件 payload MUST 包含：
```json
{
  "type": "regime_changed" | "grid_triggered" | "grid_rejected" | "manual_clear" | "engine_state",
  "strategy_id": int,
  "stock_code": str,
  "regime_id": int | null,
  "regime_name": str | null,
  "from_regime_id": int | null,
  "from_regime_name": str | null,
  "trigger_grid": {direction, step_offset, trigger_price, volume} | null,
  "current_price": float | null,
  "position_vol": int | null,
  "base_volume": int | null,
  "order_no": str | null,
  "reject_reason": str | null,
  "ts": ISO8601 string
}
```

#### Scenario: regime_changed 事件触发

- **WHEN** 策略引擎从 R1 切换到 R2（match_regime 命中 R2 + cooldown 通过）
- **THEN** MUST broadcast `strategy_update {type: 'regime_changed', from_regime_id: 1, regime_id: 2, ...}`

#### Scenario: grid_triggered 事件触发

- **WHEN** engine 下单成功（broker 返回 order_no）
- **THEN** MUST broadcast `strategy_update {type: 'grid_triggered', trigger_grid, order_no, ...}` 在 audit 写入**之后**

#### Scenario: grid_rejected 事件触发

- **WHEN** 网格被拒触发（底仓保护 / max_fires 达上限 / cooldown）
- **THEN** MUST broadcast `strategy_update {type: 'grid_rejected', reject_reason: 'base_floor_protected' | 'max_fires_reached' | 'grid_cooldown', ...}`

#### Scenario: 前端订阅与 audit 更新

- **WHEN** 前端 WS 客户端收到 `strategy_update`
- **THEN** ws.js 路由到 strategy store 的 `applyEvent(payload)`，prepend audit 行到对应 strategy

#### Scenario: 鉴权

- **WHEN** 未登录 user 订阅 `strategy_update` 频道
- **THEN** ws endpoint MUST 拒绝（沿用既有 JWT 鉴权中间件）