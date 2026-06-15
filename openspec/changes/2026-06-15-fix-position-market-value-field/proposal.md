# Fix Position.market_value Field (v4 Bug)

## Why

v4 (`cc7b67a`) 实施 11 张表时，`Position` ORM 漏了 `market_value` 字段，但代码多处引用：
- `server/api/positions.py:64` — `r.market_value`
- `server/services/push_handlers.py:222` — `pos.market_value`

后果：
- `/api/positions` 端点**完全炸**（AttributeError）
- pos_cfm push handler **写入路径异常**（用 try/except 吞了，没崩但数据丢失）

当前绕路：`holdings-read-local-db` change 用 `cost × total` 代理计算 `market_value`。**临时的**，不是根治。

## What

新增 `Position.market_value` 字段（`Float`，nullable），3 步：

1. **ORM** 加字段
2. **reconcile + push handler** 写入路径补上（不强行计算，前端 quote store 重算更准）
3. **API 层** 去掉代理代码，恢复 `r.market_value` 直读

## 设计决策

- `market_value` 字段**留 nullable**（历史数据不补，老行显示 None）
- 写入策略：**不**在 push handler / reconcile 里计算市值（成本代理不准确）
  - 真实市值由前端 quote store 实时算
  - 字段仅作"最后一次行情快照"，由定时任务（v7+）更新
- 兼容：API 层 `r.market_value or r.cost * r.total`（优先 DB 字段，回退代理）

## 风险

- DB schema migration：SQLite 加列需 `ALTER TABLE` 或 drop+create。**测试**用 `Base.metadata.create_all` 自动建新列，无需手写 migration
- 已有 evtrade.db 需 `rm -f` 重建（用户环境）

## 影响面

- 改：`server/models/orm.py`（+1 字段）
- 改：`server/api/positions.py`（去掉代理）
- 改：`server/services/push_handlers.py`（去掉 try/except）
- 改：`server/api/holdings.py`（去掉代理，与 positions 保持一致）
- 改：`server/test_holdings_api.py`（恢复 market_value 字段 seed）
- 改：`server/test_positions_api.py`（新增 — 覆盖 positions 端点 v4 未测）
- 改：`openspec/changes/archive/2026-06-15-holdings-read-local-db/` 归档说明（追加后续 fix）

## 不在范围内

- 行情定时任务写入 market_value（v7+ 单独 change）
- 持仓历史市值曲线（v7+）
