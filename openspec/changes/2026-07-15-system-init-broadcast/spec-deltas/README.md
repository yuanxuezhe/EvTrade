# Spec Deltas — 2026-07-15-system-init-broadcast

> 三处增量：system-init（数据流补 init_completed 推送）、push（频道表新增 system_update）、frontend（前端路由契约）

---

## 1. `openspec/specs/system-init/spec.md`

### ADD: REQ-INIT-003.1 日初成功后 ws 推 init_completed

**插入位置**：REQ-INIT-003 数据流图末尾（在 `WS 推 {...}` 那一行**之后**，REQ-INIT-004 之前）。

```markdown
### REQ-INIT-003.1: 日初成功后 ws 推 init_completed

- **WHEN** `POST /api/admin/sys-status/init` 成功（`result.ok=True` 且 RPC 不全失败，即 `rpc_status != 'failed'`）
- **THEN** 后端通过 `ws_manager.broadcast('system_update', ...)` 推送 1 帧：
  ```json
  {
    "type": "init_completed",
    "trd_date": "20260715",
    "report_id": 123,
    "status": "ok",
    "ts": "2026-07-15T15:30:00"
  }
  ```
- **AND** 不阻塞 HTTP 响应（`asyncio.ensure_future` 调度，与现有 `services/push/dispatcher.py::_broadcast_trade_cfm` 范式一致）
- **AND** `status` 字段语义：`'ok'` = 全部 RPC 成功；`'partial'` = 部分 RPC 失败但交易日仍切成功
- **AND** 失败通道：`rpc_status='failed'`（全部 RPC 失败）→ 不推送，前端 AppHeader 刷新按钮兜底
- **AND** `reconcile_only` 端点 (`POST /api/admin/sys-status/reconcile`) **不**推送（仅生成报告不切日）

#### Scenario: 全成功

- **WHEN** `do_reconcile` 返回 `ok=True, applied=True, error=None`
- **THEN** 推 `status='ok'`，所有持仓/资金数据已落 DB

#### Scenario: 部分 RPC 失败但交易日切成功

- **WHEN** `do_reconcile` 返回 `ok=True, applied=True, error='qry_positions: timeout'`（positions 拉取失败但 asset 成功）
- **THEN** 仍推 `status='partial'`，前端刷新但可能持仓数缺失

#### Scenario: 全部 RPC 失败

- **WHEN** `do_reconcile` 返回 `ok=False, error='全部 RPC 失败: ...'`
- **THEN** **不**推送，前端 AppHeader 按钮兜底

#### Scenario: 仅生成对账报告（manual mode）

- **WHEN** `POST /api/admin/sys-status/reconcile` 调用
- **THEN** **不**推送（持仓无变化）
```

### REQ-INIT-005 (新增)：仅生成对账报告不推送

```markdown
### REQ-INIT-005: reconcile_only 不推送

- **WHEN** `POST /api/admin/sys-status/reconcile` 端点（仅 manual 模式生成报告）
- **THEN** **不**推送 init_completed（持仓无变化，无需刷新）

#### Scenario

- **WHEN** admin 调 reconcile_only
- **THEN** 仅刷新 SystemInit 页内的 `loadReports()`，不通知其他 tab
```

---

## 2. `openspec/specs/push/spec.md`

### MODIFIED: REQ-PUSH-002 事件路由表

**原表**（第 23–28 行）：

| Func 字段 | 事件 | 路由到 WS 频道 | 前端处理 |
|---|---|---|---|
| `ord_cfm` | 委托状态变更/成交 | `order_update` | 替换 store 中同 order_no 的项；**status 字段是后端本地推断结果**（见 REQ-PUSH-005） |
| `trd_cfm` | 成交回报 | `trade_update` | 追加到 trades 列表 |
| ... | ... | ... | ... |

**新增表项**（system-init 事件，不是 push 事件，但走同一 ws 框架）：

| 触发源 | 事件 | 路由到 WS 频道 | 前端处理 |
|---|---|---|---|
| 日初成功 (`init_trading_day`) | `init_completed` | `system_update` | `holdings.refreshAll()` + `asset.fetchAsset()` + `position.fetchPositions()`（REQ-INIT-003.1） |

### ADD: REQ-PUSH-006 system_update 频道

```markdown
### REQ-PUSH-006: system_update 频道

- 后端 `server/ws/manager.py` `active_connections` 注册 `system_update: Set[WebSocket]`
- 用途：服务端主动推送"系统级事件"（日初完成、对账失败等），与行情/委托/成交增量推送并列
- 端点：`ws://host:8000/ws/system_update`，鉴权与现有频道一致（JWT token query param）
- 前端订阅方式：`wsStore.connectChannel('system_update')`，无需 stock_codes

#### Scenario: 新 ws 连接 system_update 频道

- **WHEN** 前端 `ws.connectToChannel('system_update')`
- **THEN** ws 进入 `system_update` 频道（注册到 active_connections）
- **AND** 之后所有 `ws_manager.broadcast('system_update', payload)` 均能收到
```

---

## 3. `openspec/specs/frontend/spec.md`

### ADD: REQ-FE-INIT-001 ws init_completed → 刷新持仓缓存

```markdown
### REQ-FE-INIT-001: 收到 init_completed 触发 store 刷新

- **WHEN** ws 收到 `{type:'init_completed', trd_date, ...}` payload
- **THEN** 前端 `client/src/stores/ws_dispatch.js::_onInitCompleted(data)` 触发：
  1. `useHoldingsStore().refreshAll()` — 并行 4 RPC（asset / positions / orders / trades）写缓存
  2. `useAssetStore().fetchAsset()` — 资金刷新（兼容老 view，holdings 已含 cachedAsset 但 store 桥接另算）
  3. `usePositionStore().fetchPositions()` — 持仓刷新（同上兼容）
- **AND** 不弹 toast / 不弹 Notification（静默刷新，与 AppHeader 按钮行为对齐）
- **AND** 失败由 `holdings.refreshAll()` 内部 refCounts 守门，不抛异常到 UI

#### Scenario: init_completed 全量刷新

- **WHEN** 后端推 init_completed (status='ok')
- **THEN** 持仓页 / 资金页数字立即更新（无需点 AppHeader 刷新按钮）

#### Scenario: 双保险 — HTTP 200 同步刷新 + ws 推送

- **WHEN** SystemInit.vue::handleInit 收到 HTTP 200
- **THEN** **也**直接调一次 refreshAll（不依赖 ws 推送成功）
- **AND** ws init_completed 到达后**再**调一次 refreshAll（最终一致性）
- **AND** 两次 refreshAll 内部幂等（refCounts 已就位时跳过）

#### Scenario: ws 未连接 / 推送丢失

- **WHEN** 用户 ws 断开（refreshAll 已弹错）
- **THEN** handleInit 同步刷新路径保证持仓页更新
- **AND** 下次 ws 重连后 init_completed 不会重放（fire-and-forget，无重试）
```