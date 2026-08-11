# tasks — strategy-order-design 实施清单

> 依据 [proposal.md](proposal.md) 与 [设计文档](../../../../docs/superpowers/specs/2026-08-11-strategy-order-design.md) 拆解。
> 按依赖排序：迁移 → 后端 → strategy_exec → 前端 → 测试 → 知识库归档。

## 1. DB 迁移（幂等）

- [ ] 1.1 `2026-08-11-add-strategy-order.py`：
  - 探测 `INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='strategy_order'`，缺则 `CREATE TABLE strategy_order(...)`（7 列 + 3 索引：UNIQUE(task_id) / KEY(user_id) / KEY(strategy_id)）
  - `INSERT IGNORE INTO order_no_seq(seq_name, last_value) VALUES ('strategy_order', 0)`
  - `orders.strategy_type` 列 COMMENT 更新为 `0=普通单 1=快速做T 2=策略下单`（`ALTER TABLE orders MODIFY COLUMN strategy_type TINYINT NOT NULL DEFAULT 0 COMMENT '...'`）
- [ ] 1.2 `server/tables/strategy_order.py` 通过 `tables-codegen` 生成（经临时目录避 `__init__.py` 覆盖），`server/tables/__init__.py` 追加导入
- [ ] 1.3 `server/schema.yml` 同步：新增 `strategy_order` 表 + `order_no_seq` 增 `strategy_order` 行 + `orders.strategy_type` COMMENT
- [ ] 1.4 迁移幂等自测：dev 重建 DB + 复跑 2 次不抛错 + 复跑后表结构与 `order_no_seq` 行不变

## 2. 后端 — `orders.strategy_type` 扩到 2

- [ ] 2.1 `server/api/orders/schemas.py`：`strategy_type: Literal[0, 1]` → `Literal[0, 1, 2]`，`OrderOut.strategy_type` 注释更新
- [ ] 2.2 `server/models/orm.py`：`Order.strategy_type` column comment 同步（如 ORM 维护 comment）
- [ ] 2.3 单测：`tests/server/orders/test_place_strategy_type_2.py` — `place_order(strategy_type=2)` 通过 + `strategy_type=3` 422

## 3. 后端 — signal_consumer 改用 parent_task_id

- [ ] 3.1 `server/services/strategy/signal_consumer.py`：BUY/SELL 下单请求改为
  - `task_id = payload.get("parent_task_id") or None`
  - `user_def = payload.get("strategy_name") or ""`
  - `strategy_type = 2`
- [ ] 3.2 保持：回测信号（`mode == 'backtest'` 或 `parent_task_id is None`）仍跳过、INFO 仍跳过
- [ ] 3.3 单测：`tests/server/strategy/test_signal_consumer.py` —
  - BUY signal with `parent_task_id=42, strategy_name='s1'` → place 请求含 `task_id=42, user_def='s1', strategy_type=2`
  - 回测 signal (`mode='backtest'`) → 跳过
  - INFO signal → 跳过
  - `parent_task_id=None` live signal → 走回测分支跳过（**注**：此为方案 B 强约定的已知行为，proposal 风险 2）

## 4. 后端 — strategy_exec 信号链路（外部服务，4 文件）

- [ ] 4.1 `strategy_exec/signal/types.py`：`Signal` 加
  - `parent_task_id: Optional[int] = None`
  - `strategy_name: str = ""`
  - `signal_to_payload` 用 `asdict` 自动序列化，无需额外处理
- [ ] 4.2 `strategy_exec/engines/backtrader/adapter.py`：`_set_task_meta` 加 2 个默认参数；`_publish` 构造 Signal 时带上
- [ ] 4.3 `strategy_exec/engines/backtrader/live.py`：`LiveRunner.__init__` + `start_live_runner` 透传 `parent_task_id` / `strategy_name`；`_run` 里 `_set_task_meta` 传入
- [ ] 4.4 `strategy_exec/api/internal.py`：`RunTaskRequest` 加 `parent_task_id: Optional[int] = None` + `strategy_name: Optional[str] = None`；live 分支透传给 `start_live_runner`
- [ ] 4.5 验证：回测路径签名兼容（`parent_task_id`/`strategy_name` 默认 `None`/`""`，v125 纯回测行为不变）

## 5. 后端 — 母单 REST（script_strategy.orders）

- [ ] 5.1 `server/api/script_strategy/schemas.py` 追加：
  - `StrategyOrderCreate(strategy_id: int)`
  - `StrategyOrderOut`（含 task_id / strategy_id / strategy_name / stock_code / status / active_task_id / run_count / last_started_at / last_stopped_at / 子单数 / 时间戳）
  - `StartStopResponse(task_id, status, active_task_id)`
- [ ] 5.2 `server/services/script_strategy/strategy_orders.py`：6 个服务函数
  - `create_strategy_order(db, user, strategy_id)` — 校验 owner / best_params / 生成 task_id / INSERT
  - `list_strategy_orders(db, user, is_admin)` — JOIN 策略 + 子单数 COUNT
  - `get_strategy_order(db, user, is_admin, id)` — 详情
  - `start_strategy_order(db, user, is_admin, id)` — 校验状态 / 读 best_params / `create_task(mode='live')` / 转发 `/internal/run-task` / 改 status
  - `stop_strategy_order(db, user, is_admin, id)` — 校验 running+active_task_id / 转发 `/internal/stop-task` / 改 status
  - `close_strategy_order(db, user, is_admin, id)` — 校验非 running / 改 status=closed
- [ ] 5.3 `server/api/script_strategy/strategy_orders.py`：6 个 REST 端点（路由 `POST /strategy-orders`、`GET /strategy-orders`、`GET /strategy-orders/{id}`、`POST /strategy-orders/{id}/start|stop|close`），错误码用 `STRATEGY_NOT_FOUND`（404）/ `NO_BEST_PARAMS`（400）/ `INVALID_STATE`（409）/ `FORBIDDEN`（403）
- [ ] 5.4 `server/services/script_strategy/__init__.py` + `server/api/script_strategy/__init__.py` 统一入口导出
- [ ] 5.5 单测 `tests/server/strategy/test_strategy_orders.py`：
  - 状态机：create→start→stop→close；非法转移（running 再 start / 非 running stop / running close）→ 409
  - 权限：他人私有策略建母单 → 404；他**人公开**策略建母单 → 403（best_params 不外露）
  - `best_params` 空 → 400 `NO_BEST_PARAMS`（建时 + start 时两处）
  - `task_id` 来自 `order_no_seq.strategy_order` 生成器，且 UNIQUE 不冲突
  - start 时 `strategy_task.params` 取自 `strategy.best_params`（断言转发 `/internal/run-task` 请求体）

## 6. 前端 — 新页 StrategyOrder.vue（4 面板）

- [ ] 6.1 `client/src/views/StrategyOrder.vue` 新建，路由 `/strategy-order` 在 `client/src/router/index.js` 注册
- [ ] 6.2 面板 1「策略下单」：下拉选自己的策略（**仅 `best_params` 非空可选中**；空时置灰 + 提示「需先回测出最佳参数」）；显示标的 / 「已回测」标记 / 「创建母单」按钮
- [ ] 6.3 面板 2「行情面板」：复用 `client/src/components/QuotePanel.vue`，跟随选中母单/策略的 `stock_code` 联动
- [ ] 6.4 面板 3「策略母单」：`GET /api/script-strategy/strategy-orders` 列表，每行 = task_id / 策略名 / 标的 / 状态徽章 / run_count / 子单数 / [启动|停止] / 关闭；选中行联动面板 4
- [ ] 6.5 面板 4「委托子单」：`holdings.orders.filter(o => o.strategy_type===2 && Number(o.task_id)===选中母单.task_id)`（T0Trade 同款本地缓存过滤，实时跟随 WS 推送）
- [ ] 6.6 `client/src/api/script_strategy.js` 追加 `strategyOrders.create / list / get / start / stop / close` 封装
- [ ] 6.7 `client/src/components/layout/NavBar.vue`（桌面）加「策略下单」入口 → `/strategy-order`（BottomNav 不加）
- [ ] 6.8 状态徽章：`stopped`=默认 / `running`=进行中 / `closed`=已关闭；`running` 禁用「关闭」，`closed` 禁用「启动」

## 7. 前端 — T0Trade 防御过滤

- [ ] 7.1 `client/src/views/T0Trade.vue` 委托过滤（≈470 行）加 `strategy_type !== 2` 条件
- [ ] 7.2 单测 `tests/client/views/T0Trade.test.js` 追加：T0 委托 + 同 `task_id` 策略子单同时存在 → 策略子单被过滤掉

## 8. 测试与回归

- [ ] 8.1 迁移脚本幂等自测（任务 1.4 已覆盖）
- [ ] 8.2 后端全量：`pytest tests/server/strategy/ tests/server/orders/` 全绿（除 `test_migration_idempotent.py` 2 个预存失败，见 project_v125_followups）
- [ ] 8.3 前端：`tests/client/views/StrategyOrder.test.js` 覆盖 4 面板渲染 + 状态徽章 + 互斥过滤；`tests/client/views/T0Trade.test.js` 互斥断言
- [ ] 8.4 strategy_exec：回测路径 `parent_task_id` 默认 `None` 行为不变（已有测试应通过）；live 路径 `parent_task_id`/`strategy_name` 透传单测
- [ ] 8.5 回归：v125 纯回测（无 best_params 拒绝 / 公开策略不可回测 / 私有策略 404）行为不变

## 9. 知识库归档

- [ ] 9.1 `openspec/specs/strategy/spec.md` REQ-STRAT-020 已追加（前置已做）
- [ ] 9.2 `openspec/specs/data-model/spec.md` §14 `orders.strategy_type` 列表追加 `2=策略下单`
- [ ] 9.3 `openspec/specs/strategy-exec/spec.md` REQ-SE-005（Signal）加 `parent_task_id` + `strategy_name` 字段；REQ-SE-008（LiveRunner）说明母单透传
- [ ] 9.4 实施完成、`pytest` 全绿后：`mv openspec/changes/2026-08-11-strategy-order-design openspec/changes/archive/2026-08-11-strategy-order-design`
