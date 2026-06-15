# DB seed defaults at startup

## 1. Why

EvTrade v4 commit `cc7b67a`（2026-06-14）引入了 11 张表的本地持久化层，但
**`init_db()` 只建表不种数据**。当前缺陷：

- **用户表**：admin 用户由 `main.py:on_startup` 内联创建 — 业务初始化逻辑
  散落在 main 而非 db 层，违反单一职责。
- **配置表 4 张**（`trading_session` / `fee_config` / `reconcile_config` /
  `order_no_seq`）：均为 `CheckConstraint("id = 1")` 单行表，启动后**完全为空**。
  后果：
  - `get_reconcile_config()` 第一次调时**懒加载创建**（reconcile.py:29-37）—
    不一致：有的配置懒加载，有的还得 admin 手动建。
  - `fee_config` / `trading_session` / `order_no_seq` 无任何懒加载，admin
    调 `GET /api/fee-config` 直接 500（NoneType）。
  - T0 配平 `get_fee_config()` 调 .first() 拿到 None → 计算全部 None。
- **trading_day**：被 `require_trading_day` 屏障拦死，下单全部 503。
  修复方式不统一：admin 人工调 `/api/admin/trading-day/init`（涉及 RPC，
  不可 seed）。

结果：系统**冷启动后必失败**，必须等 admin 手动建配置 + 触发对账才能
下单。开发体验差，CI 集成测试无法跑。

## 2. What

把 seed 逻辑集中到 `server/db.py`，main.py 只调一个 `init_db()`：

- **`seed_default_admin()`**：users 表为空时插入 admin/admin123。
- **`seed_default_config()`**：4 张单行配置表为空时插入默认值：
  - `trading_session`：A 股默认 09:15-11:30 / 13:00-15:00
  - `fee_config`：万一佣金 / 千 1 印花税 / 0.1% 滑点 / 最低 5 元
  - `reconcile_config`：默认人工对账，自动时以柜台为准
  - `order_no_seq`：8 位起 10000000

**TradingDay 不 seed**（需要 RPC 对账才能激活，**显式职责分离**）。

## 3. Design Decisions

| 决策 | 选择 | 原因 |
|---|---|---|
| seed 行为 | **idempotent**（count==0 才插入） | 用户运行时改配置后重启**保留** |
| seed 位置 | `db.py` 而非 `main.py` | 单一职责，db 层自洽 |
| TradingDay seed | **不**自动 | 需要 RPC（qry_positions 等），冷启动无依赖 |
| API 暴露 min_commission | 暂时**不**（保留 ORM 字段但不路由） | YAGNI，前端 v5 未用 |
| 测试隔离 | **不**改 | 已知问题：pytest fixture 共享 `evtrade.db` 文件名（v4 弱点） |

## 4. Out of Scope

- TradingDay 自动激活（需要 cron + RPC health check，超出 v4 范围）
- 测试 fixture 临时 db（v4 弱点，v6 再修）
- Seed CLI 命令行脚本（init_db() 内联足够）
- min_commission API 暴露（前端未用）

## 5. Risks

- **重启覆盖风险**：idempotent 设计保护用户改值，但若用户**删**了某行配置
  （如 `DELETE FROM trading_session`），重启**会**自动重建 — 这是
  feature，不是 bug。
- **idempotency race**：两个 backend 实例同时启动 → 都看到 count==0 → 两次
  insert → unique violation。SQLite 单文件多进程本就脆弱，**已知风险不处理**。

## 6. Success Criteria

- 删 `evtrade.db` → restart → 4 张单行配置表 + 1 行 admin 全部存在
- admin/admin123 登录 200 OK
- 启动日志有 `[SEED] Created default ...` 标记（5 条）
- TradingDay 表仍为空（验证**未**自动激活）
- 修改某行配置（如 fee_config.commission_rate=0.0002）→ restart → 值**保留**
