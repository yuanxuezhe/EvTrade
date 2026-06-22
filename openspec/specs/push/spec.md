# push — 柜台主动推送 → WebSocket 路由

> 📖 **字段映射**详见 [`data-model/spec.md`](../data-model/spec.md) §1（落库字段）

## Purpose

QMT 柜台通过 RabbitMQ 主动推送（`EvTrade.Test.Push` 队列）异步通知状态变化。
后端 RPC 客户端必须把这些 push 消息按事件类型路由到对应的 WebSocket 频道。

## Requirements

### REQ-PUSH-001: 监听 Push 队列

- RPC 客户端 `start()` 时启动 push listener
- 队列名：`EVTRADE_QUEUE_PUSH`（默认 `EvTrade.Test.Push`）
- 收到消息后根据 `func` 字段判断事件类型

### REQ-PUSH-002: 事件路由

| Func 字段 | 事件 | 路由到 WS 频道 | 前端处理 |
|---|---|---|---|
| `ord_cfm` | 委托状态变更/成交 | `order_update` | 替换 store 中同 order_no 的项；**status 字段是后端本地推断结果**（见 REQ-PUSH-005） |
| `trd_cfm` | 成交回报 | `trade_update` | 追加到 trades 列表 |
| `qry_pos` 等查询响应 | ❌ **不应在 push 出现** | — | 忽略，**应被 reply 队列消费** |

### REQ-PUSH-003: WS 频道 → 前端 store

- `order_update` → `client/src/stores/holdings.js:applyOrderPush` 替换 orders 中同 order_no 的项
- `trade_update` → 追加到 trades
- `position_update` → 重拉（push 当前未路由）
- `asset_update` → 重拉（push 当前未路由）

### REQ-PUSH-005: status 字段语义（v6，本地推断）

- 后端 `handle_ord_cfm` / `handle_trd_cfm` 写入 Order.status 时，**统一调用 `_infer_order_status` 本地推断**，不直接抄 broker 推送的 status
- WS `order_update` 推送的 status 字段 = DB 中的 status 字段 = 本地推断结果
- **前端契约**：
  - 前端 `inferOrderStatus(order, brokerStatus?)` 必须与后端 `_infer_order_status` **逐行一致**（同函数同输入同输出）
  - 前端 store 收到 `order_update` 时，对每条 order 调一次前端 `inferOrderStatus` 重算（防御性，避免与后端实现分叉）
  - 视图层（Trade.vue / Orders.vue）的 status 分组集合（`_PENDING_NUMERIC` / `_FILLED_NUMERIC` / `countByStatus`）必须用**后端本地推断码**：49/50/51/52/53/54/55/56（不是 broker 原始码 55/56 等）
- **后端函数位置**：`server/services/push_handlers.py:_infer_order_status`
- **前端函数位置**：`client/src/utils/format.js:inferOrderStatus`
- **v8 修订**：前端不再信任 broker / WS payload 的 status 字段（broker 原始码与本地推断码语义不完全一致，例如 broker 55=部成 vs 本地 50=部成）。前端展示态由 `client/src/stores/holdings.js:_recomputeStatus` 统一按 `traded_volume / volume` 推断（不传 brokerStatus），详见 REQ-FE-006

### REQ-PUSH-006: 异步落库（v8）

- push listener 调用 `handle_push(db, func, row, ts)` 时，**必须**走 `asyncio.to_thread(...)` 包裹，**禁止**在 event loop 中直接同步执行 SQLAlchemy
- 原因：push 消息密集到达时同步 SQL 操作阻塞 event loop，导致 reply 队列消费延迟、WebSocket 推送卡顿
- 实现：push listener 内部用 `await asyncio.to_thread(_run_handle_push, func, row, ts)`，helper 在新线程中新建 SessionLocal + handle_push + commit
- 错误处理：to_thread 内异常被 listener 捕获，打 error 日志（已存在），**不重试**（broker 推过的消息不会再来）
- 向后兼容：`handle_push` 同步签名不变，test_push_handlers.py 现有 11 用例继续通过

### REQ-PUSH-007: 推送按 (activeTrdDate, order_no) 匹配（v8）

#### 权威日注入（后端）

- **唯一权威**：`server/api/system.py::GET /api/system/active-day` 返激活交易日
  - 查 `SysStatus` 表 `status='active'` 的 `trd_date`
  - 响应 `{code: 0, msg: "ok", list: [{trd_date: "YYYYMMDD", status: "active"}]}`，拦截器解包后 `data[0].trd_date`
  - **不**复用 `/api/trading/clock`（flat object，非 RPC 风格）
- `server/rpc/client.py::_listen_pushs` 在 broadcast 前，用权威日**覆盖** broker 推的 trd_date（broker 偶尔推隔夜老委托）
  - `_resolve_active_trd_date_safe` 短连接 helper：动态导入 `from db import SessionLocal`，异常降级为 None
  - 注入位置：payload.data（在 broadcast 之前）+ 持久化 row（在 handle_push 之前）
  - **None 降级**：helper 异常不中断 push 链路

#### 前端守门

- `client/src/stores/holdings.js::applyOrderPush/applyTradePush` 在 merge 前校验：
  - `if (activeTrdDate.value && row.trd_date && row.trd_date !== activeTrdDate.value) return`
  - 缺 `row.trd_date`（broker 旧版本透传字段名不同）放行，**只拒绝明确的非激活日**
- `activeTrdDate` 在 `bootstrap` 第 1 步拉，失败降级为 null（push 守门不拦）
- **匹配键**：`order_no`，WS payload 兜底 `row.order_no || row.remark`（v6 `order-pk-by-orderno` 决定）

详见归档 `archive/2026-06-21-order-push-trd-date-authority/spec-deltas/push.md`

### REQ-PUSH-004: 健壮性

- 解析失败的 push 消息打 warning 日志，不影响后续消息
- 未知 `func` 字段 → 忽略 + warning 日志
- WS 客户端断开时 push listener 不受影响

## Scenarios

### S-PUSH-001: 成交回报

Given 委托 12345 部分成交 100 股 @ 12.34  
When 柜台 push `trd_cfm` 消息  
Then 后端解析后 push 到 WS 频道 `trade_update`  
And 前端 `trades` store 追加 `{trade_id, order_id, stock_code, volume:100, price:12.34, ...}`

### S-PUSH-002: 委托状态变更（本地推断后）

Given Order 初始 `volume=100, traded_volume=0, status="49"`
When 柜台 push `trd_cfm` `{order_id:"12345", volume:50}`（累计 50/100）
Then 后端 `handle_trd_cfm` 累加 `traded_volume=50` 并调 `_infer_order_status` → `status="50"`（部成）
And WS 频道 `order_update` 推 `{order_no:"...", status:"50", traded_volume:50, ...}`（**50 是本地推断码，不是 broker 码**）
And 前端 store 替换 orders 中同 order_no 的项；前端 store 调前端 `inferOrderStatus` 防御性重算确认 `status="50"`

### S-PUSH-003: Push 误路由到 qry_pos

⚠️ **已知问题**：QMT 端有时把 ord_cfm 路由到 `qry_pos` 队列名  
Then 解析时只有 `{code, msg}` 字段，没有 stock_code/evt_type  
Action: 打 warning 日志，**不重派**（避免循环）

### S-PUSH-004: push 落库不阻塞 event loop（v8）

Given push listener 收到 1 条 `ord_cfm`（handle_push 内部 SQLAlchemy 同步操作 50ms）  
When 主线程同时处理 1 个 RPC reply（0.5ms 应答）  
Then reply 消费延迟 < 5ms（不被 push 阻塞）  
And `handle_push` 在子线程执行（to_thread 包裹）

## Push 消息结构

```
func=ord_cfm
RS1: [{code: 0, msg: ""}]
RS2: [{
    order_id: "...",
    stock_code: "...",
    order_type: "23"|"24",
    volume: ...,
    price: ...,
    price_type: ...,
    status: "48"-"57"|"255",
    traded_volume: ...,
    traded_price: ...,
    order_time: "HH:MM:SS",
    remark: "..."        # v5: 柜台透传字段 (= 本地 order_no)
    status_msg: "..."    # 废单原因 / 撤单原因
}]
```

**v5 匹配规则**：`handle_ord_cfm` 先按 `order_id` 匹配本地 Order；未命中再用 `remark` (= `order_no`) 兜底匹配（应对 broker 端重新生成 `order_id` 但透传 `remark` 不变的场景）。

**v7 落库调整**（`handle_trd_cfm`）：
- 落 `Trade` 时**不再写 `order_id`**（broker 号在成交回报到达时可能尚未到达）
- 用 `order_no`（解析 `remark` 字段得到）作为 Trade PK 第二段（PK = `(trd_date, order_no, trade_id)`）
- 若 `remark` 解析失败 → 打 warning 日志，跳过该条成交（不要让一条缺关联的成交写入）

## Known Issues (from analysis)

- 🟡 `position_update` 和 `asset_update` 频道路由待完善
- 🟡 `func=qry_pos` 误路由问题根因是 QMT 端，不在本项目修复范围但需健壮处理
- 🟡 push handler `handle_pos_cfm` 不写 `market_value`（Position ORM 无此列，前端实时计算）
- 🟢 push listener 的解析器 `_parse_ord_cfm` 散落在 `client.py`，应统一为 `rpc-protocol` 能力
