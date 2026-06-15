# Proposal: 日初全流程 E2E（切日 + 写本地 + 查询本地）

## Why

用户明确要求 3 条核心契约：

1. **日初切日完必须更新到交易日表**（TradingDay upsert：close 老的 active → 当前日 upsert active）
2. **日初 init 必须从柜台 RPC 拉资金/持仓/委托/成交 → 写到本地 DB 对应表**
3. **查询（资金/持仓/委托/成交）必须查本地 DB，不调 RPC**

现状（v4 → v5 → v6 迭代后）：
- ✅ 3 点的核心实现已完成（do_reconcile → _apply_broker_data + upsert）
- ✅ /api/asset /api/positions /api/holdings /api/orders /api/trades 全部走 DB
- ❌ **没有 end-to-end 测试** 验证"RPC 拉 → DB 写 → 查询"完整链路
- ❌ **没有 regression test** 验证"同日多次 init 不累积多行 TradingDay"
- ❌ TradingDay ORM 缺 `unique(current_date)` 约束（upsert 靠代码 select-then-update，不是 DB 约束）

## What Changes

### 修改
- **`server/models/orm.py`**: `trading_day` 表加 `UniqueConstraint("current_date", name="uq_trading_day_current_date")`（DB 层级防同日多 active）
- **`server/services/reconcile.py:170-189`**: 切日时先尝试 db.commit() 后查，再处理（不变，但加注释说明 upsert 语义）

### 新增
- **`server/test_reconcile_e2e.py`**: 8-10 个测试
  - `test_e2e_full_flow`: mock RPC 返 4 类数据 → do_reconcile → 验 DB 4 表有数据 + TradingDay active + 老的 closed
  - `test_upsert_same_day`: 同日 2 次 init → TradingDay 仍 1 行 active（不是 2 行）
  - `test_init_switch_day`: 第一次 init 20260614 → 第二次 init 20260615 → 验 2 行 + 老的 closed
  - `test_apply_manual_mode`: auto_reconcile=False → RPC 拉了但 DB 不写（仅报告）
  - `test_query_local_only`: do_reconcile 完后 GET /api/asset 返 200 + 数据 = DB 里的（非 RPC）
  - `test_rpc_failure_all`: 4 类 RPC 全失败 → 返 ok=False + 不切日
  - `test_rpc_partial`: 2 类失败 → 写报告 + 503 + 不切日
  - `test_trading_day_unique_constraint`: 直接 INSERT 同 current_date 第二行 → IntegrityError

## Risk

- **加 unique 约束需删 DB 重建**（SQLite 无 ALTER ADD CONSTRAINT），dev DB 可接受
- 测试用 monkeypatch mock RPC（qry_orders/qry_trades/qry_positions/qry_asset），**不连真柜台**
- 不改生产路径，只加约束 + 测试

## Out of Scope

- 改 RPC 协议
- 改路由契约
- 改前端
- 加 alembic 正式 migration（用 DELETE FROM 重建 dev DB）
