# tasks.md — 实施 checklist

> 配套 [proposal.md](./proposal.md) + [design.md](./design.md)。每完成一项就勾上 [x]，并用一行 commit 提交。

## Phase 1 — 骨架（1 天）

### 1.1 目录与配置

- [ ] 建 `strategy_exec/` 顶层目录
- [ ] 写 `strategy_exec/pyproject.toml`（依赖：fastapi / uvicorn / sqlalchemy / pymysql / aio-pika / backtrader / pandas）
- [ ] 写 `strategy_exec/.env.example`（参考 design.md §8.1）
- [ ] 写 `strategy_exec/README.md`（启动 + 配置 + 调试指南）
- [ ] 写 `strategy_exec/.gitignore`

### 1.2 入口与启动

- [ ] `strategy_exec/strategy_exec/main.py`（FastAPI app 入口）
- [ ] `strategy_exec/strategy_exec/config.py`（Pydantic Settings，从 .env 读）
- [ ] `strategy_exec/scripts/evctl_strategy_exec.py`（仿 evctl.py，start/stop/status/restart）
- [ ] `strategy_exec/Dockerfile`（python:3.11-slim 多阶段构建）
- [ ] **验证**：本地 `python -m strategy_exec.main --port 8001` 能启动，`GET /health` 返 200

### 1.3 Mock API endpoints

- [ ] `strategy_exec/strategy_exec/api/internal.py`（4 endpoint 全部 mock 返）
- [ ] `strategy_exec/strategy_exec/api/health.py`（`/health` endpoint）
- [ ] **验证**：`curl -X POST http://localhost:8001/internal/run-task -H 'X-Internal-Token: test'` 返 mock JSON

## Phase 2 — Backtrader 引擎（1.5 天）

### 2.1 Backtrader 安装 + 项目适配

- [ ] `pip install backtrader`（或 `uv add`）
- [ ] `pyproject.toml` 添加 backtrader 依赖
- [ ] 验证：`python -c "import backtrader; print(bt.__version__)"`

### 2.2 数据访问层（data_access）

- [ ] `strategy_exec/strategy_exec/data_access/db.py`（SQLAlchemy engine，复用 EVTRADE_DB_URL）
- [ ] `strategy_exec/strategy_exec/data_access/strategy_script.py`（按 user_id + script_id 复合 PK 读）
- [ ] `strategy_exec/strategy_exec/data_access/strategy_task.py`（读 + 写，含乐观锁 version 字段）
- [ ] `strategy_exec/strategy_exec/data_access/strategy_audit.py`（写 strategy_script_audit）
- [ ] **验证**：单元测试 db.py 能连 MySQL 并读 strategy_task

### 2.3 信号层（signal）

- [ ] `strategy_exec/strategy_exec/signal/types.py`（Signal / SignalType dataclass + payload 序列化）
- [ ] `strategy_exec/strategy_exec/signal/publisher.py`（RabbitMQ publish with publisher confirms）
- [ ] 单元测试 test_publisher.py（用 mock broker）

### 2.4 适配层（adapter）

- [ ] `strategy_exec/strategy_exec/engines/backtrader/adapter.py`（ProjectStrategy 基类，buy_signal/sell_signal 方法）
- [ ] `strategy_exec/strategy_exec/engines/backtrader/adapter.py`（notify_signal_published 回调）
- [ ] 单元测试 test_adapter.py（buy_signal 触发 publish_signal）

### 2.5 回测引擎（backtest）

- [ ] `strategy_exec/strategy_exec/market_data/hq_history.py`（broker his_hq 走 RabbitMQ，参考 v90 实现）
- [ ] `strategy_exec/strategy_exec/engines/backtrader/backtest.py`（Backtrader.cerebro.run 封装）
  - 加载用户脚本 → bt.Strategy 子类
  - 加 data feed（来自 hq_history.bars）
  - 跑 run() → 收集 signals
  - 写 backtest_result / best_params / progress
- [ ] 默认模板 `strategy_exec/strategy_exec/templates/default_bt_strategy.py`（双均线策略）
- [ ] 单元测试 test_backtest.py（金叉→BUY, 死叉→SELL）

### 2.6 实盘引擎（live）

- [ ] `strategy_exec/strategy_exec/market_data/hq_ws_client.py`（直连 hqserver WS，订阅 stock_code）
- [ ] `strategy_exec/strategy_exec/engines/backtrader/live.py`（Backtrader live data feed + asyncio loop）
- [ ] live_signals 环形缓冲（限 500 条，每 5s flush DB）
- [ ] 单元测试 test_live.py（mock WS → on_tick → buy_signal）

### 2.7 沙箱（sandbox）

- [ ] `strategy_exec/strategy_exec/sandbox/loader.py`（动态 import 用户脚本）
- [ ] 安全约束：禁用 `os.system` / `subprocess` / `open`（仅允许 bt.Strategy 子类 + 自定义方法）

## Phase 3 — EvTrade 集成（1 天）

### 3.1 EvTrade 端 signal_consumer

- [ ] `server/services/strategy/signal_consumer.py`（aio_pika 订阅 EvTrade.StrategySignal）
- [ ] 收到 BUY/SELL signal → POST `/api/orders/place`
- [ ] 幂等: trace_id 去重（24h TTL）
- [ ] 单元测试 test_signal_consumer.py（mock message → mock place_order）

### 3.2 EvTrade 端 forwarding endpoint

- [ ] `server/api/script_strategy/endpoints.py` `run_task_endpoint` 改转发
  - 权限校验（current_user.id == task.user_id || admin）
  - 校验状态 != running
  - UPDATE strategy_task SET status='queued', execution_service='strategy_exec'
  - HTTP POST `strategy_exec:8001/internal/run-task`（带 X-Internal-Token）
  - 返 202 + task 详情
- [ ] 同理改 `stop_task_endpoint`
- [ ] 集成测试 test_forwarding.py（httpx_mock 验证）

### 3.3 EvTrade main.py startup

- [ ] `server/main.py` startup 事件中 `asyncio.ensure_future(signal_consumer.start())`
- [ ] shutdown 事件中 `signal_consumer.stop()`

### 3.4 EvTrade progress 回调（方案 2，可选）

- [ ] `server/api/internal/strategy_exec_callback.py`（POST `/api/internal/strategy-exec/progress`）
- [ ] `server/main.py` 注册 router
- [ ] **决策**：若 strategy_exec 直接写 DB strategy_task.progress，**不需要**此回调（信号推送已触发 ws_manager.broadcast 'task_progress_update'）

### 3.5 集成测试

- [ ] 端到端 smoke 测试（脚本创建→运行→signal→EvTrade 下单）
- [ ] 验证 progress 正确推前端 ws_manager
- [ ] 验证 RabbitMQ 故障兜底（publisher confirm 失败 → 写 error_msg）

## Phase 4 — 清理旧引擎（1 天）

### 4.1 DB schema 迁移

- [ ] `server/migrations/2026-08-09-strategy-task-exec-fields.py`（3 字段幂等添加）
- [ ] 跑 `python scripts/sync_schema.py apply` 同步 ORM
- [ ] 验证：`DESCRIBE strategy_task` 含 execution_service / execution_pid / version

### 4.2 删除旧引擎代码

- [ ] 删 `server/strategy/service.py`（999 行）
- [ ] 删 `server/strategy/runtime/backtest.py`
- [ ] 删 `server/strategy/runtime/live.py`
- [ ] 删 `server/strategy/runtime/grid.py`
- [ ] 删 `server/strategy/runtime/sandbox.py`
- [ ] 删 `server/strategy/runtime/fast_data.py`
- [ ] 删 `server/strategy/runtime/his_hq.py`
- [ ] 删 `server/strategy/runtime/risk.py`
- [ ] 删 `server/strategy/lib/trading.py`（doorder / docancel）
- [ ] 删 `server/strategy/templates/default_script.py`
- [ ] 删 `server/strategy/tests/test_backtest.py` + `test_his_hq.py` + `test_sandbox.py` + `test_indicators.py`
- [ ] 简化 `server/strategy/__init__.py`（仅保留 indicators 工具）

### 4.3 验证清理结果

- [ ] 全仓 grep `server.strategy.runtime\|server.strategy.service` → 无引用
- [ ] 全仓 grep `lib.doorder\|lib.docancel\|SignalRecorder\|make_trading_facade` → 无引用
- [ ] 前端编译通过 (`cd client && npm run build`)
- [ ] 后端启动通过 (`python -m uvicorn server.main:app`)
- [ ] 现有 75 个 server 测试通过 (`pytest server/test_*.py`)

## Phase 5 — 文档 + 归档（1 天）

### 5.1 用户脚本迁移指南

- [ ] `docs/strategy-migration-v90-to-bt.md`（v90 ctx.lib.doorder → Backtrader self.buy_signal 迁移指南）
- [ ] 包含 3 个典型例子（双均线 / 突破策略 / 多标的轮动）
- [ ] 包含迁移前后代码对照表

### 5.2 strategy_exec README

- [ ] `strategy_exec/README.md`（启动 + 配置 + 调试）
  - 启动：`python -m strategy_exec.main --port 8001`
  - 调试：RabbitMQ / MySQL / hqserver 连接测试
  - 日志：`/var/log/strategy_exec.log`
  - 常见问题 FAQ

### 5.3 更新 spec 文档

- [ ] 新建 `openspec/specs/strategy-exec/spec.md`（独立能力文档）
  - REQ-SE-001: 独立部署
  - REQ-SE-002: 4 internal endpoints
  - REQ-SE-003: Backtrader 引擎
  - REQ-SE-004: 信号推送（RabbitMQ）
  - REQ-SE-005: 用户脚本接口（bt.Strategy 适配层）
  - REQ-SE-006: 沙箱安全约束
- [ ] 更新 `openspec/specs/strategy/spec.md`
  - 删除 REQ-STRAT-014~017（v90 script-strategy 模块）
  - REQ-STRAT-001~013 网格策略保持
  - 加 §"已迁移到独立服务"指针
- [ ] 更新 `openspec/specs/data-model/spec.md`
  - strategy_task 加 3 字段说明
  - strategy_script / strategy_script_audit 写权限说明（EvTrade 只读 / strategy_exec 可写）
- [ ] 更新 `openspec/specs/configuration/spec.md`
  - 加 4 新 env（STRATEGY_EXEC_API_URL / STRATEGY_EXEC_API_TOKEN / EVTRADE_STRATEGY_EXCHANGE_NAME / EVTRADE_STRATEGY_SIGNAL_QUEUE）

### 5.4 提交与归档

- [ ] commit 1: docs(specs): 新建 strategy-exec spec + 更新 strategy/data-model spec
- [ ] commit 2: feat(strategy_exec): 骨架 + Backtrader 集成（独立可启动）
- [ ] commit 3: feat(evtrade): signal_consumer + 转发 endpoint
- [ ] commit 4: refactor(evtrade): 删旧 strategy engine（service.py + runtime/*）
- [ ] commit 5: chore(schema): strategy_task +3 字段迁移
- [ ] `mv openspec/changes/2026-08-09-strategy-exec-service openspec/changes/archive/2026-08-09-strategy-exec-service`
- [ ] `git push origin master`（待用户拍板）

### 5.5 部署验证（dev 环境）

- [ ] 启动 EvTrade (`python -m uvicorn server.main:app --port 8000`)
- [ ] 启动 hqserver (`python -m hq.hqserver`)
- [ ] 启动 strategy_exec (`python -m strategy_exec.main --port 8001`)
- [ ] 前端 ScriptTask.vue 创建脚本 + 启动回测 → 验证 signal 推送 + audit 落库
- [ ] 前端 ScriptTask.vue 启动实盘 → 验证 tick → signal → EvTrade 下单 → 委托回报

---

## ✅ 完成定义（DoD）

- [ ] strategy_exec 独立服务可启动，4 endpoint 全部正常
- [ ] Backtrader 回测跑通（默认金叉策略能生成 BUY/SELL signal）
- [ ] Backtrader 实盘跑通（订阅 tick → 触发 signal → 推送 RabbitMQ）
- [ ] EvTrade signal_consumer 订阅 signal → 调 `/api/orders/place` 成功
- [ ] 前端 ScriptTask.vue 0 改动仍正常工作
- [ ] 旧 strategy 引擎代码全删
- [ ] DB schema 迁移完成（3 新字段）
- [ ] 所有 server 测试通过
- [ ] 所有 strategy_exec 测试通过
- [ ] 文档完整（SPEC + README + migration guide）
- [ ] 归档 change 完成

---

## ⚠️ 阻塞项 / 风险

| 风险 | 缓解 |
|---|---|
| Backtrader 安装失败 | pyproject.toml 锁版本, 本地先验证再 commit |
| RabbitMQ broker 故障 | publisher confirm + 重试 3 次 + 写 error_msg |
| MySQL 写竞争 | strategy_task.version 乐观锁 |
| Backtrader 与现有 sandbox 行为差异 | 单元测试覆盖所有现有用户脚本 case |
| EvTrade 部署中断（删除旧代码瞬间）| 灰度: 双服务并行 1 周, signal_consumer 先观察不回真实订单 |