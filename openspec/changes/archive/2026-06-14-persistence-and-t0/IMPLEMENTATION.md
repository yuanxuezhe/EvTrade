# Persistence + T0 — v4 实施归档

> 实施日期: 2026-06-14 ｜ 状态: ✅ 已完成（42/42 步，pytest 75/75 全绿）

## 概要

把 EvTrade 从「RPC 透传网关」改造为「本地 DB 优先 + RPC 写入」：
- **业务数据源**：本地 SQLite（11 张新表）
- **下单/撤单**：本地先 INSERT，再调柜台 RPC
- **推送**：4 类 push 事件自动落库
- **查询**：纯 DB SELECT，不调 RPC
- **屏障**：未做日初 / 非交易时段 → 503（查询不受限）
- **日初**：admin 人工触发对账 + 切交易日
- **T0**：配平系数 + 整手取整 + 费率可配

## 测试统计

| 测试文件 | 通过/总数 | 覆盖 |
|----------|----------|------|
| hq/test_hqserver.py | 18/18 | 行情订阅 |
| server/test_models.py | 13/13 | 11 张表 ORM |
| server/test_order_no.py | 2/2 | 8 位本地 order_no |
| server/test_guards.py | 14/14 | 屏障层 |
| server/test_orders_api.py | 11/11 | 下单/撤单/查询 API |
| server/test_push_handlers.py | 9/9 | 4 类 push 落库 |
| server/test_reconcile.py | 8/8 | 对账 + 日初 + 报告 |
| server/test_t0.py | 11/11 | 配平系数 + 整手 + 费率 |
| **合计** | **86/86** | |

## 新增路由

| Method | Path | 说明 |
|---|---|---|
| POST | /api/orders/place | 标准下单（先 DB 后 RPC） |
| POST | /api/orders/place_t0 | T0 一键（自动取整） |
| POST | /api/orders/place_t0_pair | T0 一买一卖（智能配平） |
| DELETE | /api/orders/{id} | 撤单（调 RPC，不本地改 status） |
| GET | /api/orders | 委托列表（默认激活日） |
| GET | /api/orders/history?trading_day= | 任意交易日历史 |
| GET | /api/positions | 持仓（DB） |
| GET | /api/trades | 成交（DB） |
| GET | /api/asset | 资金（DB） |
| GET | /api/trading/clock | 时段+交易日状态（前端轮询） |
| GET | /api/fee-config | 费率 |
| PATCH | /api/fee-config | 改费率（admin） |
| POST | /api/admin/trading-day/init | 日初 + 对账（admin） |
| GET | /api/admin/trading-day | 历史交易日（90 天） |
| GET | /api/admin/trading-day/active | 当前激活日 |
| GET | /api/admin/reconcile/config | 对账配置 |
| PATCH | /api/admin/reconcile/config | 改 auto_reconcile |
| GET | /api/admin/reconcile/reports | 对账报告列表（90 天） |
| GET | /api/admin/reconcile/reports/{id} | 单个报告详情 |
| GET | /api/admin/trading-session | 时段配置 |
| PATCH | /api/admin/trading-session | 改时段（admin） |

## 新增表（11 张）

- `orders` - 委托（status 48/49/55/已撤等）
- `trades` - 成交
- `positions` - 持仓（按 TRD_DATE+stock_code 唯一）
- `assets` - 资金（单行 id=1）
- `quote_snapshots` - 行情快照
- `fee_config` - 费率（单行 id=1）
- `trading_day` - 交易日（status: pending/active/closed）
- `trading_session` - 交易时段（单行）
- `reconcile_config` - 对账配置（单行）
- `reconcile_report` - 对账历史报告
- `order_no_seq` - order_no 序号（单行 + 原子 UPSERT）

## 实施阶段

1. Phase 1 数据层（4 步）
2. Phase 2 屏障层（4 步）
3. Phase 3 写路径（5 步）
4. Phase 4 push 处理（4 步）
5. Phase 5 trades/positions/asset + 对账 + 日初（8 步）
6. Phase 6 T0 + 配平系数 + 费率（6 步）
7. Phase 7 归档（1 步）

详见 `tasks.md` 42 步清单。
