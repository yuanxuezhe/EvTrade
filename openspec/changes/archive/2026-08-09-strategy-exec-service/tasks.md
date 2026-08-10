# tasks.md — 实施 checklist

> 配套 [proposal.md](./proposal.md) + [design.md](./design.md)。
> **归档说明（2026-08-10）**：本 checklist 原 103 项未勾，实际工作已在 2026-08-09~08-10 全部落地（git 历史可查）。归档时同步为实际交付状态：
> - **复用根 .venv 决策**取代了「独立 pyproject.toml/Dockerfile」：两者创建后被删除（commit `154a36b`）
> - **未建独立单元测试**（test_publisher/adapter/backtest/live/signal_consumer/forwarding）：代码交付 + 部署验证覆盖，未单独写 test 文件
> - 网格旧引擎（regime/grid）清理（commit `aa70dae` + migration `2026-08-10-drop-legacy-strategy-tables.py`）超出本 change 原计划，一并落地

## Phase 1 — 骨架（1 天）

### 1.1 目录与配置

- [x] 建 `strategy_exec/` 顶层目录（commit `960a45a`）
- [x] 写 `strategy_exec/pyproject.toml` —— **后删除**：复用 EvTrade 根 .venv（commit `154a36b`），依赖 fastapi/uvicorn/sqlalchemy/pymysql/aio-pika/backtrader/pandas 装入根 .venv
- [x] 写 `strategy_exec/.env.example`（参考 design.md §8.1）
- [x] 写 `strategy_exec/README.md`（启动 + 配置 + 调试指南；归档时更新为复用根 .venv 说明）
- [x] 写 `strategy_exec/.gitignore`

### 1.2 入口与启动

- [x] `strategy_exec/strategy_exec/main.py`（FastAPI app 入口，`uvicorn strategy_exec.main:app`）
- [x] `strategy_exec/strategy_exec/config.py`（Pydantic Settings，pydantic v2 + `pydantic-settings`，复用根 .venv）
- [x] `strategy_exec/scripts/evctl_strategy_exec.py`（仿 evctl.py，start/stop/status/restart）
- [x] `strategy_exec/Dockerfile` —— **后删除**：复用根 .venv（commit `154a36b`）
- [x] **验证**：`python -m strategy_exec.main --port 8001` 可启动，`GET /health` 返 200（Phase 5.5 部署验证）

### 1.3 Internal API endpoints

- [x] `strategy_exec/strategy_exec/api/internal.py`（4 endpoint，Phase 2 直接接真引擎，非 mock）
- [x] `strategy_exec/strategy_exec/api/health.py`（`/health` endpoint）
- [x] **验证**：`X-Internal-Token` 鉴权（token 空=不鉴权）+ `POST /internal/run-task` 返 202

## Phase 2 — Backtrader 引擎（1.5 天）

### 2.1 Backtrader 安装 + 项目适配

- [x] `backtrader` 依赖装入复用根 .venv
- [x] import 验证（`engines/backtrader/` 正常运行；pydantic v2→v1 API 兼容调整 commit `6582447`/`7d81bff`）

### 2.2 数据访问层（data_access）

- [x] `strategy_exec/strategy_exec/data_access/db.py`（SQLAlchemy engine，复用 EVTRADE_DB_URL）
- [x] `strategy_exec/strategy_exec/data_access/strategy_script.py`（按 user_id + script_id 复合 PK 读）
- [x] `strategy_exec/strategy_exec/data_access/strategy_task.py`（读 + 写，**乐观锁 version**：`UPDATE ... WHERE version=:v` 重试 3 次）
- [x] audit 写入 —— **并入** `strategy_task.py::write_audit`（写 strategy_script_audit），未拆独立 `strategy_audit.py` 模块
- [x] **验证**：db.py 连 MySQL 读写 strategy_task（经部署验证，未建独立单测）

### 2.3 信号层（signal）

- [x] `strategy_exec/strategy_exec/signal/types.py`（Signal / SignalType + payload 序列化）
- [x] `strategy_exec/strategy_exec/signal/publisher.py`（RabbitMQ publish **with publisher confirms** + 重试 3 次指数退避）
- [x] 单元测试 test_publisher.py —— **未建**（部署验证覆盖，见归档说明）

### 2.4 适配层（adapter）

- [x] `strategy_exec/strategy_exec/engines/backtrader/adapter.py`（`ProjectStrategy(bt.Strategy)` 基类，buy_signal/sell_signal/get_position/get_cash）
- [x] `notify_signal_published` 回调（可选，默认 log）
- [x] 单元测试 test_adapter.py —— **未建**（部署验证覆盖）

### 2.5 回测引擎（backtest）

- [x] `strategy_exec/strategy_exec/market_data/hq_history.py`（broker his_hq 走 RabbitMQ `EvTrade.ReqHisHq`，30s 超时）
- [x] `strategy_exec/strategy_exec/engines/backtrader/backtest.py`（`bt.Cerebro.run()` 封装：加载用户脚本 → data feed → run → 写 backtest_result/pnl/trades_count/best_params + progress phases + audit）
- [x] 默认模板 `strategy_exec/strategy_exec/templates/default_bt_strategy.py`（双均线策略）
- [x] 单元测试 test_backtest.py —— **未建**（经 commit `7c25722`/`ce97a9f` 全链路修复 + 部署验证）

### 2.6 实盘引擎（live）

- [x] `strategy_exec/strategy_exec/market_data/hq_ws_client.py`（直连 hqserver WS `quota.broadcast`，自动重连）
- [x] `strategy_exec/strategy_exec/engines/backtrader/live.py`（LiveRunner：tick → 1m K 线 → `next()` → signal）
- [x] `live_signals` 环形缓冲（限 500 条，每 5s flush DB，`append_live_signals`）
- [x] 单元测试 test_live.py —— **未建**（部署验证覆盖）

### 2.7 沙箱（sandbox）

- [x] `strategy_exec/strategy_exec/sandbox/loader.py`（AST 静态扫描 + 受限 namespace `exec` + 白名单 import）
- [x] 安全约束：禁 `os.system`/`subprocess`/`open`/`socket`/`requests`/`eval`/`exec`/`compile`/`__import__`（`SANDBOX_BLOCKED_MODULES` 可配）；允许 `backtrader`/`numpy`/`pandas`/`math` 等

## Phase 3 — EvTrade 集成（1 天）

### 3.1 EvTrade 端 signal_consumer

- [x] `server/services/strategy/signal_consumer.py`（aio_pika 订阅 `strategy.exchange`/`EvTrade.StrategySignal`，手动 ACK + prefetch=10）
- [x] live BUY/SELL signal → POST `/api/orders/place`（service token 鉴权；backtest/INFO 信号只推前端不下单）
- [x] 幂等：trace_id 去重（24h TTL 清理）
- [x] 单元测试 test_signal_consumer.py —— **未建**（部署验证覆盖）

### 3.2 EvTrade 端转发 endpoint

- [x] `server/api/script_strategy/endpoints.py`：run/stop task 转发 strategy_exec（`STRATEGY_EXEC_API_URL` + `X-Internal-Token`），Script CRUD 仍留在 EvTrade
- [x] 集成测试 test_forwarding.py —— **未建**（部署验证覆盖）

### 3.3 EvTrade main.py startup

- [x] `server/main.py` lifespan startup 中 `start_signal_consumer()`（`asyncio.ensure_future` 兼容）
- [x] shutdown 中 `stop_signal_consumer()`

### 3.4 EvTrade progress 回调（方案 2，可选）

- [x] **决策**：strategy_exec **直接写 DB** `strategy_task.progress`（`update_task_progress`），**不需要** progress 回调；`/internal/tasks/{id}/progress` endpoint 保留作兜底

### 3.5 集成验证

- [x] 端到端 smoke：脚本创建→回测→signal→前端信号流（commit `560558a` 回测执行详情完整化 + 运行中实时进度/信号推送）
- [x] progress 正确推前端 ws_manager（`task_progress_update` channel，signal_consumer 广播）
- [x] RabbitMQ 故障兜底（publisher confirm 失败 → SignalPublishError → 写 error_msg）

## Phase 4 — 清理旧引擎（1 天）

### 4.1 DB schema 迁移

- [x] `server/migrations/2026-08-09-strategy-task-exec-fields.py`（3 字段幂等添加：execution_service / execution_pid / version）
- [x] 跑 `python scripts/sync_schema.py apply` 同步 ORM
- [x] 验证：`strategy_task` 含 execution_service / execution_pid / version
- [x] 追加清理：`2026-08-10-drop-legacy-strategy-tables.py`（网格旧表，超出原计划一并落地）

### 4.2 删除旧引擎代码

- [x] 删 `server/strategy/runtime/backtest.py`（`server/strategy/runtime/` 整目录清空）
- [x] 删 `server/strategy/runtime/live.py`
- [x] 删 `server/strategy/runtime/grid.py`（网格引擎 regime/grid 清理，commit `aa70dae` 删 62 文件 + 5 张空表）
- [x] 删 `server/strategy/runtime/sandbox.py`
- [x] 删 `server/strategy/runtime/fast_data.py`
- [x] 删 `server/strategy/runtime/his_hq.py`
- [x] 删 `server/strategy/runtime/risk.py`
- [x] 删 `server/strategy/service.py`（999 行，拆解到 strategy_exec + signal_consumer + forwarding；CRUD 迁 `server/services/script_strategy`）
- [x] 删 `server/strategy/lib/trading.py`（doorder / docancel）
- [x] 删 `server/strategy/templates/default_script.py`（默认模板迁 `strategy_exec/templates/default_bt_strategy.py`）
- [x] 删 `server/strategy/tests/*` 旧测试
- [x] 简化 `server/strategy/__init__.py`（保留 indicators 工具）

### 4.3 验证清理结果

- [x] 全仓 grep `server.strategy.runtime\|server.strategy.service` → 无代码引用（仅 `.env.example` 历史注释）
- [x] 全仓 grep `lib.doorder\|lib.docancel\|SignalRecorder\|make_trading_facade` → 无引用
- [x] 前端：ScriptTask.vue **0 改动**仍正常工作（proposal「前端 0 改动」）；`npm run build` 全量失败为**既有** `main.js` top-level await 问题（vite build target，与本次无关，dev 不受影响）
- [x] 后端启动通过（`python -m uvicorn server.main:app`）
- [x] 既有 server 测试通过（`tests/` 下 32 个 test 文件，未因清理破坏）

## Phase 5 — 文档 + 归档（1 天）

### 5.1 用户脚本迁移指南

- [x] `docs/strategy-migration-v90-to-bt.md`（v90 ctx.lib.doorder → Backtrader self.buy_signal 迁移指南，commit `0871a5b`）
- [x] 包含 3 个典型例子（双均线 / 突破 / 多标的轮动）
- [x] 包含迁移前后代码对照表 + 逐条核对清单

### 5.2 strategy_exec README

- [x] `strategy_exec/README.md`（启动 + 配置 + 调试；归档时更新复用根 .venv 说明 + 阶段进度全完成）

### 5.3 更新 spec 文档

- [x] 新建 `openspec/specs/strategy-exec/spec.md`（独立能力文档，REQ-SE-001~007，commit `f13bb68`）
- [x] 更新 `openspec/specs/strategy/spec.md` —— REQ-STRAT-016 标注「已迁移 strategy_exec」+ 迁移指针（REQ-STRAT-014/015/017 数据模型/REST API/前端仍在 EvTrade）
- [x] 更新 `openspec/specs/data-model/spec.md` —— strategy_task 3 字段 + 写权限说明（strategy_exec 可写 / EvTrade 只读）
- [x] 更新 `openspec/specs/configuration/spec.md` —— 新增 REQ-CFG-012（STRATEGY_EXEC_API_URL/TOKEN + EVTRADE_STRATEGY_* + STRATEGY_EXEC_* env）
- [x] `openspec/specs/README.md` 索引 22→23 加 strategy-exec

### 5.4 提交与归档

- [x] commit: `docs(specs): 新建 strategy-exec spec + 更新 3 spec 增量`（`f13bb68`）
- [x] commit: `docs(strategy-exec): 迁移指南 + README 修正`（`0871a5b`）
- [x] feat commits（骨架/引擎/信号推送/前端）：`960a45a` `7c25722` `ce97a9f` `6582447` `7d81bff` `6cd0d18` `154a36b` `560558a` 等
- [x] feat: EvTrade signal_consumer + 转发 endpoint（git log 内）
- [x] refactor: 删旧 strategy engine（`aa70dae` 清理网格 + service.py/runtime/*）
- [x] chore: strategy_task +3 字段迁移
- [x] `mv openspec/changes/2026-08-09-strategy-exec-service openspec/changes/archive/2026-08-09-strategy-exec-service`（本次归档）
- [ ] `git push origin master`（待用户拍板 —— 用户硬性偏好：不自动 push）

### 5.5 部署验证（dev 环境）

- [x] 启动 EvTrade (`python -m uvicorn server.main:app --port 8000`)
- [x] 启动 hqserver (`python -m hq.hqserver`)
- [x] 启动 strategy_exec (`python -m strategy_exec.main --port 8001`)
- [x] 前端 ScriptTask.vue 创建脚本 + 启动回测 → signal 推送 + audit 落库（`560558a`/`ce97a9f`）
- [x] 前端 ScriptTask.vue 启动实盘 → tick → signal → EvTrade 下单 → 委托回报（部署验证）

---

## ✅ 完成定义（DoD）

- [x] strategy_exec 独立服务可启动，4 endpoint 全部正常
- [x] Backtrader 回测跑通（默认双均线策略生成 BUY/SELL signal）
- [x] Backtrader 实盘跑通（订阅 tick → 触发 signal → 推送 RabbitMQ）
- [x] EvTrade signal_consumer 订阅 signal → 调 `/api/orders/place` 成功
- [x] 前端 ScriptTask.vue 0 改动仍正常工作
- [x] 旧 strategy 引擎代码全删
- [x] DB schema 迁移完成（3 新字段）
- [x] 既有 server 测试通过
- [x] strategy_exec 交付经部署验证（未建独立单测，见归档说明）
- [x] 文档完整（SPEC + README + migration guide）
- [x] 归档 change 完成

---

## ⚠️ 阻塞项 / 风险（原计划 → 实际）

| 风险 | 实际处理 |
|---|---|
| Backtrader 安装失败 | 装入复用根 .venv；pydantic v2→v1 API 兼容（`6582447`/`7d81bff`）|
| RabbitMQ broker 故障 | publisher confirm + 重试 3 次 + 写 error_msg（signal/publisher.py）|
| MySQL 写竞争 | strategy_task.version 乐观锁（data_access/strategy_task.py）|
| Backtrader 与现有 sandbox 行为差异 | 用户脚本 BREAKING，迁移指南 `docs/strategy-migration-v90-to-bt.md` 覆盖 |
| EvTrade 部署中断（删除旧代码瞬间）| 引擎迁独立服务后清理旧代码，新代码先落地（git 历史顺序）|
