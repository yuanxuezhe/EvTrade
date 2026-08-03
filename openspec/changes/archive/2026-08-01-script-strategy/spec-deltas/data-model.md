# spec-delta: data-model

新增 2 张表,与现有 strategy/* 表解耦。

## strategy_script (策略脚本)

| 字段 | 类型 | 说明 |
|---|---|---|
| id | int PK auto | |
| user_id | int | 所属用户 |
| name | varchar(64) | 脚本名(用户视角唯一) |
| code | longtext | 用户编写的 Python 脚本源码 |
| params_schema | json | 参数定义数组 `[{"key": "fast", "type": "int", "default": 5, "min": 1, "max": 60, "step": 1}, ...]` |
| description | varchar(255) | 备注 |
| status | varchar(16) | active / paused / deleted |
| created_at / updated_at | datetime | |

## strategy_task (任务运行)

| 字段 | 类型 | 说明 |
|---|---|---|
| id | int PK auto | |
| user_id | int | |
| script_id | int FK strategy_script.id | 关联脚本 |
| stock_code | varchar(16) | 标的 |
| mode | varchar(8) | `backtest` / `live` |
| status | varchar(16) | pending / running / done / stopped / failed |
| params | json | 实际运行的参数值(回测为单组,实盘为 backtest best_params) |
| backtest_result | json | `{pnl, win_rate, sharpe, trades_count, equity_curve[]}` (回测模式填) |
| best_params | json | 回测选优后的最优参数(回测模式填) |
| backtest_start_date / end_date | varchar(8) | 回测时间窗 |
| period | varchar(8) | K 线周期: 1m / 5m / 15m / 30m / 1h / 1d |
| pnl | float | 实盘累计已实现盈亏 |
| positions | json | 实盘当前持仓快照 `{stock_code: vol}` |
| trades_count | int | 实盘成交笔数 |
| started_at / finished_at | datetime | |
| error_msg | varchar(500) | 失败原因 |
| created_at / updated_at | datetime | |

## 索引
- `strategy_task(user_id, status)` — 任务列表常用过滤
- `strategy_task(script_id, mode)` — 脚本维度的任务统计