# script-strategy — 新增前端可编写 Python 脚本策略模块(回测 + 实盘)

## Why

现有 `server/services/strategy/` 是 flag + regime + grid 的**规则引擎**模式(用户在前端配置 flag 名 + 优先级 + grid step_offset),适合"配出来的"网格做 T。

用户需要的是**另一种**策略工程范式:
- 用户在前端**编写 Python 脚本**,调用 `MA5()`/`EMA()` 等指标函数
- 脚本保留**参数占位符**(`params.fast = 5` / `params.slow = 20`),可以设取值范围
- 一键**回测**:按参数笛卡尔积遍历,每组跑历史 K 线 → 计算 PnL → 选最优参数
- 一键**实盘**:用回测最优参数订阅实时行情 → 触发下单

参考 `iquant/quota_his_test.py` 的回调链 (`on_quote` → pandas 累积 → 指标 + 信号) 思路,但**不依赖 RabbitMQ / pandas**,而是把数据流收敛到 Python 函数回调,与现有项目栈对齐。

## What Changes

### 新增
- `server/strategy/lib/` — 纯函数指标 + doorder/docancel wrapper
  - `lib/indicators.py` — `MA`, `EMA`, `RSI`, `MACD`, `BOLL`, `KDJ`, `ATR`, `BARSLAST` (条件首次成立距今)
  - `lib/trading.py` — `doorder(stock_code, side, price, volume)`, `docancel(order_no, trd_date)`, `get_position(stock_code)`
  - `lib/__init__.py` — 暴露给用户脚本的统一 facade
- `server/strategy/runtime/` — 脚本执行 + 回测 + 实盘运行时
  - `runtime/sandbox.py` — 用户脚本安全加载(白名单 imports + globals 限制)
  - `runtime/backtest.py` — `BacktestEngine.run(script, params, bars)` 返回 PnL/胜率/夏普等指标
  - `runtime/live.py` — `LiveRunner.run(script, params, stock_code)`,订阅 hqserver 行情,on_tick 回调
  - `runtime/grid.py` — 参数取值范围笛卡尔积展开
- `server/api/script_strategy/` — REST API
- `client/src/views/ScriptDev.vue` — 策略开发页(代码编辑器 + 参数 schema + 保存)
- `client/src/views/ScriptTask.vue` — 策略交易页(任务列表 + 新建 + 回测运行 + 实盘运行 + 收益)
- `client/src/api/script_strategy.js` — 前端 API client

### 数据
- 新表 `strategy_script`(脚本+参数 schema 元数据)
- 新表 `strategy_task`(任务运行态 + 回测结果 + best_params)

### 兼容性
- **完全独立**于 `server/services/strategy/`,不复用任何代码。新建顶层 `server/strategy/` 避免 import 冲突。
- 实盘下单走现有 `server.api.orders.ord_stk` (RPC) + `cancel_order` 路径,与手动下单共用 broker 通道。
- 历史行情走现有 hqserver `his_hq` 接口(MQ 链路已在 iquant 中验证)。

### 删除
无

## 影响面

| 模块 | 改动 |
|---|---|
| `server/tables/` | 新增 2 张表文件(由 `scripts/gen_tables.py` 自动生成) |
| `server/migrations/` | 新增 1 个 DDL 迁移 |
| `server/main.py` | 注册 `script_strategy.router` |
| `client/src/router/index.js` | 注册 2 个新路由 |
| `client/src/App.vue` | 导航菜单加入口 |

## 拍板决策(2026-08-01 用户确认)

| 决策 | 选项 | 选择 |
|---|---|---|
| 数据存储 | A 新建 2 张独立表 / B 复用 strategy 表加 type / C 1 张总表 JSON 化 | **A** |
| 目录布局 | `server/strategy/` 顶层 / `server/services/strategy_script/` 内嵌 | **顶层**(避免 import 重名) |
| 回测数据源 | A his_hq / B quote_snapshots / C 直连 xtquant | **A**(依赖 hqserver 已有数据流,改动最小) |

## 详细 spec

参见 `spec-deltas/` 下的 3 份 spec delta + `tasks.md` 的 13 步实施清单。

## 验证标准

1. `pytest server/strategy/` 新增测试覆盖 lib 指标 / sandbox / backtest
2. 前端页面打开正常,代码编辑器可保存脚本 + 运行回测任务 + 看结果表
3. 回测任务完成时 `strategy_task.best_params` 字段非空
4. 实盘任务启动后,`strategy_task.status='running'`,行情 tick 触发时调用 `doorder`,`orders` 表新增对应委托