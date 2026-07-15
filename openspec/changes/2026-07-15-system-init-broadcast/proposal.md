# 2026-07-15-system-init-broadcast — 系统初始化完成后自动推送 init_completed

## Why

当前 `SystemInit.vue` 触发日初成功后，**前端持仓页/资金页不会自动刷新**，需要用户手动点 AppHeader 的"刷新数据"按钮。原因是：

- `client/src/stores/holdings_bootstrap.js::bootstrap()` 只在 App 启动/登录后跑一次
- 资金/持仓**没有 ws 增量通道**（v22 已删 position_update / asset_update 频道，broker xtquant 不发 pos_cfm / ast_cfm）
- `sys_status.py::init_trading_day` 成功后仅返回 HTTP 响应，未推送任何 ws 信号

用户原话（2026-07-15）："检查，为什么我系统初始化完成后，还要点刷新缓存，才会更新页面上的持仓信息？帮我优化，系统初始化后，增加一个信号系统，服务端给前端发通知。系统初始化完成后，直接发送一个初始化完成的信号，前端会自动更新缓存"

`system-init/spec.md` REQ-INIT-003 数据流图里**已规划** "WS 推 {channel: 'system_update', type: 'trading_day_changed', trd_date: today}"，但实际代码没落地。本次 change 补上这个 gap。

## What Changes

新增一个 ws 信号通道 `system_update`，后端 `init_trading_day` 成功后广播 `{type: 'init_completed', trd_date, report_id, status, ts}`；前端 ws_dispatch 收到后自动调 `holdings.refreshAll()` + `asset.fetchAsset()` + `position.fetchPositions()` 刷新持仓/资金缓存。

### 核心决策（Q1-Q6 全按默认）

| # | 决策 | 结论 |
|---|---|---|
| Q1 | 方案 A/B | **A**：新增 `system_update` 频道（与 order_update/trade_update/quote_update/strategy_update 并列） |
| Q2 | 推送时机 | init_trading_day 返回 `code=0 OR partial`（`rpc_status` != `'failed'`）均推送；HTTP 响应同步发送前 `asyncio.ensure_future` 调度 |
| Q3 | 前端行为 | **a) 全量刷新**：`holdings.refreshAll()` + `asset.fetchAsset()` + `position.fetchPositions()`，与 AppHeader 行为完全一致 |
| Q4 | payload | `{type:'init_completed', trd_date:'20260715', report_id:123, status:'ok'\|'partial', ts:ISO8601}` |
| Q5 | 双保险 | `handleInit` HTTP 200 后**也**主动调一次 refreshAll（兜底：ws 断了用户也能看到最新） |
| Q6 | handleReconcile | 不推送（仅生成报告、不切交易日，持仓不需要重拉） |

### 改动文件清单

| 层 | 文件 | 改动 |
|---|---|---|
| 后端 WS | `server/ws/manager.py` | `active_connections` 字典新增 `"system_update": set()` |
| 后端路由 | `server/api/admin/sys_status.py` | `init_trading_day` 返回 `InitResponse` 前 `asyncio.ensure_future(ws_manager.broadcast('system_update', payload, trace_id=...))` |
| 前端路由 | `client/src/stores/ws_dispatch.js` | `dispatchPayload()` 新增 `t === 'init_completed'` 分支 → `_onInitCompleted` → refreshAll |
| 前端 view | `client/src/views/SystemInit.vue` | `handleInit` 成功分支追加 `holdingsStore.refreshAll()` + `asset/position fetch` 双保险 |
| OpenSpec | `openspec/specs/system-init/spec.md` | REQ-INIT-003 数据流补 `init_completed` 推送与前端响应契约 |
| OpenSpec | `openspec/specs/push/spec.md` | REQ-PUSH-002 加 system_update 频道 → init_completed 事件；REQ-PUSH-003 加前端处理 |
| OpenSpec | `openspec/specs/frontend/spec.md` | REQ-FE 新增 REQ-FE-INIT-001 描述 ws init_completed 路由 + store 刷新契约 |

### 兼容性

- **后端**：新增频道，不动现有 `order_update/trade_update/quote_update/strategy_update`；`ws_manager.broadcast` 是已有 API
- **前端**：`ws_dispatch.js` 是纯追加 if-else 分支，老 type 路由不动
- **DB**：不改任何 schema
- **协议**：payload 是 ws json 新增 type，老 ws 客户端忽略

## 跨层 commit 拆分（v21 模板）

按"按层独立可 revert"原则拆 5 个 commit：

1. **`feat(ws): 新增 system_update 频道`** — 仅 `server/ws/manager.py`
2. **`feat(api): init_trading_day 成功后广播 init_completed`** — `server/api/admin/sys_status.py` + 必要 import
3. **`feat(client): ws_dispatch 路由 init_completed → 刷新 holdings/asset/position`** — `client/src/stores/ws_dispatch.js` + `client/src/views/SystemInit.vue` 双保险
4. **`docs(spec): 补 system_update 频道与 init_completed 事件契约`** — `openspec/specs/{system-init,push,frontend}/spec.md` 三处增量
5. **`chore(archive): 归档 changeset 并跑 verify-template`** — `openspec/changes/2026-07-15-system-init-broadcast/` → `archive/`，update tracking

## 风险

| 风险 | 缓解 |
|---|---|
| ws_manager 单例跨模块 import 失败 | 沿用 `services/push/dispatcher.py` 的 lazy import `from server.ws.manager import ws_manager` 写法 |
| init handler 阻塞 | 用 `asyncio.ensure_future` 不 await，与现有 `_broadcast_trade_cfm` 一致 |
| 前端 refreshAll 引发 N 个 RPC 风暴 | `holdings.refreshAll()` 内部已用 `Promise.allSettled` 并行 + refCounts 守门，无新风险 |
| 推送失败 / ws 断开 | **双保险 Q5**：HTTP 200 后同步刷新一次；ws 是主路径，断开时降级为"用户点刷新"（现状） |
| 跨日推送冲突（同日多次 init） | broadcast 是 fire-and-forget 幂等，重复推送只导致多次 refreshAll（refreshAll 内部幂等） |

## 不在本次范围

- 不修 `/system-init` 60s 超时（用户 2026-07-15 已主动取消该任务，下次再说）
- 不改 ws 鉴权 / 握手 / 心跳
- 不改 `do_reconcile` 算法
- 不动 orders/trades ws 推送
- 不推送 `reconcile_only`（仅生成报告）的事件