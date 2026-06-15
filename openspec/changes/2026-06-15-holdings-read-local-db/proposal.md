# Holdings endpoint reads local DB

## 1. Why

v4 改造（commit `cc7b67a`，2026-06-14）把持仓数据**写入本地**：
- `pos_cfm` push handler → `positions` 表（`server/services/push_handlers.py`）
- 日初对账 `do_reconcile` → `_apply_broker_data` → 写 `positions` 表
  （`server/services/reconcile.py:194-264`）

但 **`GET /api/holdings` 端点**没改：
- 当前实现（`server/api/holdings.py:24-37`）**仍直接调 RPC `qry_positions`**
- 后果：
  - **柜台可达时**：返回 RPC 数据，DB 是空表 → 双重数据源，前端拿到 6 字段 RPC
    数据但 DB 没记录
  - **柜台不可达时**：返 -1，前端 holdings store bootstrap 失败 → 仪表盘
    持仓空白
  - 与 v4 设计契约「**本地 DB 是持仓展示源**」矛盾（`AGENTS.md` 业务数据源）

对照 `GET /api/positions`（v4 正确实现），`holdings` 是 v4 漏改的端点。

## 2. What

把 `GET /api/holdings` 从「RPC 透传」改为「**读本地 positions 表**」，保持
**6 字段响应格式不变**（兼容前端 holdings store）。

### 字段映射

| 旧 holdings 字段 | 新 holdings 字段 | 来源 |
|---|---|---|
| `stock_code` | `stock_code` | `Position.stock_code` |
| `last_vol` | `initial_position` | `Position.initial_position` |
| `volume` | `total` | `Position.total` |
| `available` | `available` | `Position.available` |
| `cost` | `cost` | `Position.cost` |
| `market_value` | `market_value` | `Position.market_value` |

### 查询参数（与 `/api/positions` 对齐）

- `stock_code` 可选：按股票代码过滤
- `trading_day` 可选：默认 = 激活日（`resolve_default_trd_date`）
- 若未做日初 → 返 503 + `code=TRADING_DAY_NOT_INIT`（与 positions 一致）

### 端点保留

- **保留** `/api/holdings`（被前端 `holdings store` 引用，6 字段格式）
- **保留** `/api/positions`（13 字段完整版，position store 用）
- 两个端点**查询同一张表**（`positions`），仅响应字段不同

## 3. Design Decisions

| 决策 | 选择 | 原因 |
|---|---|---|
| 保留 holdings 端点 | ✅ | 前端 holdings store bootstrap 依赖 |
| 字段格式 | 保留 6 字段 | 最小改动前端 |
| 字段映射 | `last_vol→initial_position`, `volume→total` | 语义对齐 |
| TradingDay 屏障 | **加** | 与 `/api/positions` 一致 |
| 调 RPC 兜底 | **不** | 数据源契约：本地 DB 唯一 |
| 删除 holdings 端点 | **不** | 与 `/api/positions` 字段不同，前端用不同 store |

## 4. Out of Scope

- 合并 `/api/holdings` 和 `/api/positions`（破坏前端，v6 大改）
- 改 holdings store 前端解析（保留 6 字段）
- 加 `user_id` 过滤（v4 已知，positions 表无 user_id，按 stock_code 聚合）
- 加 `realized_pnl` 字段（v4 已知缺失）

## 5. Risks

- **trading_day 未激活**：返 503，前端 holdings bootstrap **会失败**
  （之前 RPC 失败返 -1 不阻断）。**对策**：前端 holdings.js 已用
  `.catch` 单点错误，positions 数 0 不影响其他 3 类（asset/orders/trades）
- **DB 表为空（冷启动未对账）**：返空 list，code=0 → 仪表盘显示「持仓 0 只」
  — 这是正确行为（不是 bug）
- **push 写入 vs do_reconcile 覆盖竞态**：日初对账时 `delete+insert`，与
  push handler 同时写会**丢 push 数据**（v4 已知，do_reconcile 阶段柜台
  不会发 push，故实际不发生）

## 6. Success Criteria

- 删 `evtrade.db` → restart → 调 `/api/holdings` 返 `code=503 TRD_DATE`
- admin 调 `/api/admin/trading-day/init` → 调 `/api/holdings` 返 `code=0`
  + 持仓列表（6 字段格式）
- 调 `/api/holdings?stock_code=600000` 返单只
- 跑 `pytest server/test_*.py` 全绿
- holdings store bootstrap 仍能跑（前端不动）

## 7. Sequence

1. 修改 `server/api/holdings.py` — 1 文件
2. 写新 test `server/test_holdings_api.py` — 3 测试
3. 验证前端 holdings store 仍能 bootstrap
4. commit + push
5. 归档 change

## 8. Related

- v4 实施归档：`openspec/changes/archive/2026-06-14-persistence-and-t0/`
- positioning spec：`openspec/specs/positioning/spec.md`（本 change 改之）
- 同步 change：`2026-06-15-db-seed-defaults`（同日另一改动，不冲突）
