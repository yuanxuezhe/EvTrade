# strategy-exec-service — 策略运行独立服务化（基于 Backtrader 重构）

> **作者**: Hermes + 用户拍板 8 项决策
> **日期**: 2026-08-09
> **状态**: ✅ 已实施并归档（2026-08-10）

## 为什么改（Why）

### 问题陈述

当前 EvTrade 项目的"策略运行"能力（回测 + 实盘）有 4 个核心痛点：

1. **紧耦合**：策略运行引擎（`server/strategy/runtime/{backtest,live}.py`）与 EvTrade 主进程深度耦合，doorder/docancel 直接调用 `server.api.orders.ord_stk`（RPC + DB），无法独立部署与扩展
2. **扩展性差**：自研简易引擎（~500 行）不支持多策略并行、回测优化器、组合回测等行业标准能力
3. **资源争抢**：策略运行（特别回测）吃 CPU，与 FastAPI 请求处理、broker RPC 监听共享进程 — 回测跑 30 分钟时前端会卡
4. **职责不清**：脚本编辑器、回测、实盘、信号推送、audit 落库全在同一个 service.py (999 行) 中，难以维护

### 解决方案

1. 引入 **Backtrader** 作为底层回测/实盘引擎（业界标准，支持多策略/多标的/组合优化）
2. 把"策略运行"拆成**独立服务** `EvTrade/strategy_exec/`（不依赖 EvTrade 任何代码），与 EvTrade 通过 **RabbitMQ 推送 + HTTP REST** 通信
3. 策略运行结果以**信号**形式（buy/sell signal）通过 RabbitMQ 推回 EvTrade，EvTrade 收到信号后**自己调用 `/api/orders/place`** 下单
4. **风控 / 下单 / 落单 / 持仓推** 都还在 EvTrade 交易端，strategy_exec 只负责"算" — 职责清晰

## 范围（Scope）

### 包含（In）

| 项 | 详情 |
|---|---|
| 新增独立服务 | `EvTrade/strategy_exec/` （独立 `pyproject.toml` + `.env` + `Dockerfile`）|
| 新增 RabbitMQ 拓扑 | `strategy.exchange`（topic, durable）+ `EvTrade.StrategySignal` 队列 + `routing_key=stock_code` |
| 引入 Backtrader | `strategy_exec/engines/backtrader/` 作为唯一回测 + 实盘引擎 |
| 新增 4 个 REST endpoint（internal）| `POST /internal/run-task` / `POST /internal/stop-task` / `GET /internal/tasks/{id}/status` / `POST /internal/tasks/{id}/progress` |
| 新增 RabbitMQ consumer | `server/services/strategy/signal_consumer.py`（订阅 signal → 调 `/api/orders/place`）|
| EvTrade 转发 | `server/api/script_strategy/endpoints.py` 的 `/tasks/{id}/run` + `/tasks/{id}/stop` 改为转发到 strategy_exec |
| 删除现有引擎 | `server/strategy/runtime/{backtest,live,sandbox,grid,risk,fast_data,his_hq}.py`（保留 indicators.py 兼容）|
| 删除 service.py | `server/strategy/service.py`（999 行）拆解到 strategy_exec + signal_consumer + forwarding endpoint |
| DB schema 共享 | `strategy_script` / `strategy_task` / `strategy_script_audit` 保持单库（共用 `EVTRADE_DB_URL`）|
| 新增 spec | `openspec/specs/strategy-exec/spec.md`（独立能力文档）|
| 现有 spec 增量 | `strategy/spec.md` 标注迁移 + `data-model/spec.md` 加 strategy_exec 写权限说明 |

### 不包含（Out）

| 项 | 详情 |
|---|---|
| 现有用户脚本兼容 | **BREAKING** — 用户 Python 脚本（`on_bar` / `on_tick` / `ctx.lib.doorder`）需重写为 Backtrader `bt.Strategy.next()` + `self.buy()/self.sell()` 接口 |
| 风控移到 strategy_exec | **不在本 change 范围** — 风控继续留在 EvTrade（`server/services/risk.py` / `client/src/constants/riskProfile.js`）|
| broker RPC 直接对接 | strategy_exec **不**调 broker RPC — 只算信号，下单是 EvTrade 的事 |
| 网格策略（`server/services/strategy/quote_consumer.py` / `engine.py`）| **不在本 change 范围** — 网格策略引擎是另一条独立路径（change `strategy_trade`），与脚本策略并行存在。本 change 不动 |
| 部署自动化（CI/CD / k8s / Docker compose）| 在 docs/ 体系沉淀，本 change 只产出可启动的骨架 |

### 影响的现有能力

| Spec | 影响 |
|---|---|
| `strategy/spec.md` REQ-STRAT-014~017 | **整段删除**（v90 script-strategy 模块迁到 strategy_exec）|
| `strategy/spec.md` REQ-STRAT-011（WS strategy_update 频道）| 不动（脚本策略与网格策略共用）|
| `frontend/spec.md` REQ-FE-310（/script-task 路由）| 不动（前端 0 改动）|
| `frontend/spec.md` REQ-FE-004（WebSocket）| 不动（task_progress_update 仍走 EvTrade ws_manager 推前端）|
| `data-model/spec.md` §12 strategy_script + §13 strategy_script_audit + §8 strategy_task | 扩展字段 "execution_service" 标识（'evtrade' / 'strategy_exec'）|
| `push/spec.md` REQ-PUSH-033 | 不动（推送频道是 EvTrade 内 ws_manager 管理）|
| `configuration/spec.md` | 加 4 个 env: `EVTRADE_STRATEGY_EXCHANGE_NAME` / `EVTRADE_STRATEGY_SIGNAL_QUEUE` / `STRATEGY_EXEC_API_URL` / `STRATEGY_EXEC_API_TOKEN` |
| `system-init/spec.md` | 加 strategy_exec 服务启动健康检查 |

## 关键决策（已拍板）

| # | 决策 | 拍板人 | 备注 |
|---|---|---|---|
| Q1 | 新服务目录 `EvTrade/strategy_exec/`，**完全独立**，不依赖其他文件 | 用户 | 同仓独立部署 |
| Q2 | RabbitMQ 推送 signal（topic exchange + routing_key=stock_code）| 用户 | 复用 `EVTRADE_RABBITMQ_URL` |
| Q3 | EvTrade 收 signal → 调自家 `/api/orders/place` | 用户 | 信号与下单职责分离 |
| Q4 | ScriptTask.vue 仍调 EvTrade `/api/script-strategy/tasks/{id}/run`，EvTrade 转发 | 用户 | 前端 0 改动 |
| Q5 | **风控不在 strategy_exec** — 留在 EvTrade 交易端 | 用户 | 简化 strategy_exec 职责 |
| Q6 | 用 **Backtrader** 重构策略引擎（完全推翻现有自研引擎）| 用户 | BREAKING — 用户脚本需重写 |
| Q7 | Q4（前端调用）已拍板：EvTrade 转发 | 用户 | 见 design.md §"前端调用流"|
| Q8 | Change 名 `2026-08-09-strategy-exec-service` | 用户 | — |

## 工作量估算

| 阶段 | 工作量 |
|---|---|
| SPEC.md 评审（当前阶段）| 0.5 天 |
| Phase 1: strategy_exec 骨架 + 配置 + 启动器（独立可启动）| 1 天 |
| Phase 2: Backtrader 集成 + 信号推送（publish_signal）| 1.5 天 |
| Phase 3: EvTrade signal_consumer + 转发 endpoint | 1 天 |
| Phase 4: 删除现有 engine/service + DB schema 字段 + 迁移 | 1 天 |
| Phase 5: 测试 + 文档 + 归档 | 1 天 |
| **合计** | **6 个工作日** |

## 兼容性 & 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| **BREAKING 用户脚本** | 现有 100+ 用户脚本需重写为 Backtrader 接口 | 在 change 中提供 `strategy_exec/templates/migrate_from_v90.py` 帮助函数 + migration 文档 |
| DB schema 共享的写竞争 | strategy_exec 写 `strategy_task.progress` + EvTrade 写 `strategy_task.status` — 并发 lost update | 加 `version` 字段 + 乐观锁；update 时 `WHERE version=:v` |
| RabbitMQ 消息丢失风险 | 网络/服务故障可能丢 signal | publisher confirms + 消费侧幂等（order_no 唯一约束）|
| 双服务故障域 | EvTrade 与 strategy_exec 任一挂掉 → 整体不可用 | health check + 独立重启 + 监控（不在本 change 范围，留给部署文档）|

## 不在范围（Future / 后跟 change）

| 项 | 时机 |
|---|---|
| 网格策略（`server/services/strategy/`）也独立化 | 后续 change |
| strategy_exec 多实例部署（HA）| 后续 change |
| 策略编辑器（ScriptDev.vue）独立化 | 后续 change |
| 多策略组合优化器 | 后续 change（Backtrader 支持，1-2 天工作量）|
| 策略回测报告 Web 渲染 | 后续 change（独立 BI 模块）|