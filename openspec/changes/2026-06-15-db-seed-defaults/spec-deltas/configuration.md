# configuration — DB seed defaults delta

> This delta extends REQ-CFG-*  with database initialization semantics.
> Merged into `specs/configuration/spec.md` upon approval.

## ADDED Requirements

### REQ-CFG-006: DB 默认数据 seed

- `server/db.py:init_db()` 在建表后**自动 seed** 默认数据（仅当表为空时，幂等）。
- `server/main.py:on_startup` **仅调用 `init_db()`**，不重复写业务初始化逻辑。
- 日志前缀 `[SEED]` 标识 seed 行为。

#### Seed 内容

| 表 | 行为 | 默认值 |
|---|---|---|
| `users` | 空时插入 1 行 | username=admin, password=admin123, role=admin, full_name=系统管理员 |
| `trading_session` | 空时插入 1 行 (id=1) | morning=09:15-11:30, afternoon=13:00-15:00 |
| `fee_config` | 空时插入 1 行 (id=1) | rate=0.0001, tax=0.001, slip=0.001, min=5.0 |
| `reconcile_config` | 空时插入 1 行 (id=1) | auto=0 (manual), broker_priority=1 |
| `order_no_seq` | 空时插入 1 行 (id=1) | last_value=10000000 |
| `trading_day` | **不**自动 seed | 需 admin 调 `/api/admin/trading-day/init` 触发 RPC 对账 |

#### REQ-CFG-006.1 幂等性

- 实现方式：`SELECT COUNT(*)` → 0 时 INSERT。
- 用户运行时改某行（如 fee_config.commission_rate）→ 重启后**保留**用户改值。
- 用户**删除**某行配置 → 重启后**自动重建**（feature，非 bug）。

#### REQ-CFG-006.2 职责分离

- TradingDay 不自动 seed 的原因：需要 `qry_positions` / `qry_asset` /
  `qry_orders` / `qry_trades` 4 类 RPC 调用，依赖柜台可达性。
- 冷启动无柜台依赖时，TradingDay 留空，下单屏障会**主动拒绝**直到 admin
  触发对账。

#### REQ-CFG-006.3 日志契约

启动时每个被 seed 的表输出一行：
```
[SEED] Created default admin: admin / admin123
[SEED] Created default trading_session: 09:15-11:30 / 13:00-15:00
[SEED] Created default fee_config: rate=0.0001, tax=0.001, slip=0.001, min=5.0
[SEED] Created default reconcile_config: manual, broker-priority
[SEED] Created default order_no_seq: 10000000
```

## ADDED Scenarios

### S-CFG-004: 冷启动（空 DB）

Given 服务首次启动，`server/evtrade.db` 不存在  
When uvicorn 启动  
Then `init_db()` 创建 11 张表 + seed 5 张单行配置表（4 配置 + users）  
And 日志输出 5 行 `[SEED]`  
And `GET /api/auth/login` 用 admin/admin123 返回 200

### S-CFG-005: 重启保留用户改值

Given admin 调 `PATCH /api/fee-config { commission_rate: 0.0002 }`  
When restart.sh restart  
Then fee_config.commission_rate **仍为 0.0002**（不覆盖）  
And 日志**不**输出 `[SEED] Created default fee_config ...`（因为 count>0）

### S-CFG-006: TradingDay 不自动激活

Given 冷启动完成  
When admin 调 `GET /api/orders`  
Then 返回 503 + `code=TRADING_DAY_NOT_INIT`  
And trading_day 表**仍为空**（验证 seed 未误激活）

## MODIFIED Requirements

无（REQ-CFG-001~005 保持不变）。

## REMOVED Requirements

无。

## Out of Scope

- TradingDay 自动激活（需要 cron + RPC health check）
- 测试 fixture 临时 db（v4 已知弱点，v6 修）
- min_commission 路由暴露（前端未用）
- Seed CLI 命令行脚本
