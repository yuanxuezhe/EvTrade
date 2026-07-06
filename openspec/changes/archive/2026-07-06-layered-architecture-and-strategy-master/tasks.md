# Tasks — Layered Architecture + orders.raw_id（v13 scope 缩小版）

> **执行约束**：所有 commit 顺序固定（前序 commit 不通过则后续不可推）。每个 commit 完成后跑一次 `python -c "from server.X import Y"` 守住 import 完整性。
>
> **不修改逻辑**：CLAUDE.md + 用户明确要求。每个 task 的"行为一致性"列说明此 task 完成后用户可见行为是否变化 — 仅 task #4（加 raw_id 列）是加性增强，其余全为文件搬迁或基类抽象。
>
> **承认远程**：远程 `2026-07-05-strategy_trade` 已实现的 `server/services/strategy/` + `server/api/strategy.py` + `server/tests/strategy/*` 在本 change 全部不动。

## Commit 序列（6 commits + 1 archive）

### Commit #1 — `chore(server): 新建 server/infra/ 骨架（mq + db 基类 + 兼容垫片）`

**新增文件**：
- `server/infra/__init__.py`
- `server/infra/mq.py` — `MessageQueueClient` 类（aio_pika RMQ 长连接基类，含 `connect/publish/listen_replies/listen_pushs/close`）
- `server/infra/db.py` — `engine / SessionLocal / Base / get_db / db_session / init_db`（从 `server/db.py` 整体搬迁）

**修改文件**：
- `server/db.py` → 改为顶层 re-export 兼容垫片：`from server.infra.db import (...)`

**行为变化**：无（兼容垫片路径不变）

**验收**：
- [ ] `python -c "from server.infra.db import Base, SessionLocal, get_db, db_session, init_db"` 0 错误
- [ ] `python -c "from server.infra.mq import MessageQueueClient"` 0 错误
- [ ] `python -c "from server.db import Base, SessionLocal, get_db, db_session, init_db"` 0 错误（兼容垫片）
- [ ] `python -c "from server.main import app"` 0 错误

---

### Commit #2 — `refactor(server): RPClient 继承 MessageQueueClient（transport 减薄）`

**修改文件**：
- `server/rpc/transport.py` — `RPClient` 改为 `class RPClient(MessageQueueClient):`，删 `connect()` 中的 aio_pika 实现细节（`aio_pika.connect_robust / channel / declare_exchange / declare_queue / bind` 等），改为调用 `super().connect()` + 业务级 queue 声明（保留 reply_queue / push_queue 业务归属）
- `server/rpc/transport.py` — 删 `publish` 的 aio_pika publish 调用细节，改为 `await super().publish(...)`
- `server/rpc/transport.py` — 保留所有业务级字段（`pending: dict / _publish_confirm_timeout / _dispatcher`）+ `_listen_replies` / `_listen_pushs` / `_handle_reply` / `_safe_msg_type` / `call` / `_log_reply` / `_count_reply_rows` / `close` 全部不动

**行为变化**：无（外部接口完全保持；`get_rpc_client` / `close_rpc_client` 单例不变；test_rpc_link.py 21 用例全过）

**验收**：
- [ ] `python -c "from server.rpc.transport import RPClient, get_rpc_client, close_rpc_client, RABBITMQ_URL, EXCHANGE_NAME, QUEUE_REQ, QUEUE_REPLY, QUEUE_PUSH"` 0 错误
- [ ] `python -c "from server.rpc.client import RPClient, ord_stk, cancel_order, qry_asset, qry_orders, qry_trades, qry_positions"` 0 错误
- [ ] `python -c "from server.services.push.dispatcher import PushDispatcher"` 0 错误（远程 v1 strategy 不影响）

---

### Commit #3 — `refactor(server): 业务表 CRUD 迁 repo/（orders/trades/positions/assets/system）`

**新增文件**：
- `server/repo/__init__.py` — re-export `repo.orders / repo.trades / repo.positions / repo.assets / repo.system / repo.quote_snapshots` 顶层符号
- `server/repo/orders.py` — 从 `services/order_no.py:next_order_no` + `services/order_status.py:infer_order_status + TERMINAL_STATUSES + _INFER_RULES` 迁入；新增 `get_by_order_no / insert_pending_order / insert_cancel_row` 函数（封装 INSERT 委托行 / cancel-row 的样板）
- `server/repo/trades.py` — 从 `services/push/handlers.py` 等迁出 trades CRUD
- `server/repo/positions.py` — 从 `services/` 迁出 positions CRUD
- `server/repo/assets.py` — 从 `services/` 迁出 assets CRUD
- `server/repo/system.py` — 合并 `services/trading_clock.py` + sys_status / fee_config / reconcile_config / trading_session 的 CRUD
- `server/repo/quote_snapshots.py` — quote_snapshots CRUD

**修改文件**：
- `server/services/order_no.py` → 删除（迁 repo/）
- `server/services/order_status.py` → 删除（迁 repo/）
- `server/services/trading_clock.py` → 删除（迁 repo/）
- 所有 `from server.services.order_no import next_order_no` → 改为 `from server.repo.orders import next_order_no`
- 所有 `from server.services.order_status import infer_order_status, ...` → 改为 `from server.repo.orders import infer_order_status, ...`
- 所有 `from server.services.trading_clock import ...` → 改为 `from server.repo.system import ...`

**远程不动**：
- `server/services/strategy/`（远程 v1）— 本 commit 不动
- `server/api/strategy.py`（远程 v1）— 本 commit 不动

**行为变化**：无（纯搬迁 + import 路径改写）

**验收**：
- [ ] `python -c "from server.repo import next_order_no, infer_order_status, get_by_order_no, insert_pending_order, insert_cancel_row"` 0 错误
- [ ] `python -c "from server.services.strategy import StrategyEngine"` 0 错误（远程 v1 不动）
- [ ] `python -c "from server.services.order_no import next_order_no"` 报错 ImportError（确认旧路径已删）
- [ ] `python -m pytest server/ -v` 仍可运行（兼容旧 CLI 习惯）

---

### Commit #4 — `feat(server): orders.raw_id 列 + DELETE cancel-row 写入 raw_id（加性增强，user_def 不变）`

**新增文件**：
- `server/migrations/2026-07-06-add-orders-raw-id.py` — idempotent `ALTER TABLE orders ADD COLUMN raw_id VARCHAR(8)`（列存在则 skip）

**修改文件**：
- `server/models/orm.py` — `Order` 类追加 `raw_id = Column(String(8), nullable=True)` + 注释段（v13 NEW 段；user_def 字段保持远程 REQ-TRADE-011 三种取值并存）
- `server/api/orders/schemas.py` — `OrderOut` 加 `raw_id: Optional[str] = None`（默认 None 兼容旧数据）
- `server/api/orders/cancel.py` — **改第 2 步 INSERT cancel-row**：
  - `user_def = f"CANCEL:{orig.order_no}"`（v9 约定，不变）
  - `raw_id = orig.order_no`（v13 NEW 字段写入）
  - 其他字段不变
  - WS broadcast payload 增加 `raw_id` 字段
- `server/repo/orders.py:insert_cancel_row` — 函数签名加 `raw_id` 参数（默认 `None`，但 DELETE 端点调用时传 `orig.order_no`）

**行为变化**（加性增强）：
- 普通 strategy 委托：`raw_id=NULL`（place 流程不变）
- cancel-row：`raw_id=orig.order_no`（新增字段写入；user_def 同时保留 `"CANCEL:{orig.order_no}"` 字符串格式）
- WS `order_update` payload 多 `raw_id` 字段
- 旧 cancel-row 数据（v9-v12 期间生成的）`raw_id=NULL` 无破坏

**验收**：
- [ ] `python server/migrations/2026-07-06-add-orders-raw-id.py` 幂等（运行 2 次无报错）
- [ ] `sqlite3 server/evtrade.db ".schema orders"` 包含 `raw_id` 列
- [ ] `python -c "from server.models.orm import Order; print(Order.raw_id)"` 输出 `orders.raw_id` 字段
- [ ] `python -c "from server.api.orders.schemas import OrderOut; print(OrderOut.model_fields['raw_id'].default)"` 输出 `None`
- [ ] 手动 curl DELETE /api/orders/{order_no} → cancel-row 同时含 `user_def="CANCEL:{no}"` + `raw_id={orig.order_no}`（双重字段）
- [ ] `python -m pytest server/test_orders_api.py -v` 全过（monkeypatch 路径不变）

---

### Commit #5 — `chore(tests): 迁 server/test_*.py → tests/server/ 镜像目录（续远程 2026-07-02 未完成部分）`

**新增文件**（21 迁 + 2 新）：
- `tests/server/__init__.py`（如果远程 v1 没建）
- `tests/server/api/__init__.py` + `tests/server/api/conftest.py`（如远程 v1 没建）
- `tests/server/api/test_auth.py` (迁自 server/test_auth.py)
- `tests/server/api/test_format_ts.py`
- `tests/server/api/test_holdings_api.py`
- `tests/server/api/test_orders_api.py`
- `tests/server/api/test_system_api.py`
- `tests/server/api/test_trades_api.py`
- `tests/server/api/test_ws_endpoint.py`
- `tests/server/infra/__init__.py` + `tests/server/infra/test_db_session.py`（★ 迁到 infra 层）
- `tests/server/models/__init__.py` + `tests/server/models/test_models.py`
- `tests/server/repo/__init__.py` + `tests/server/repo/test_orders_repo.py`（覆盖 next_order_no / infer_order_status / insert_pending_order / insert_cancel_row；迁自 services/test_order_no.py + 改名）
- `tests/server/rpc/__init__.py` + `tests/server/rpc/conftest.py`（mock MQ fixture）+ `tests/server/rpc/test_rpc.py` + `tests/server/rpc/test_rpc_link.py`
- `tests/server/services/__init__.py` + `tests/server/services/test_logflow.py` + `tests/server/services/test_guards.py` + `tests/server/services/test_config.py` + `tests/server/services/test_push_async.py` + `tests/server/services/test_push_handlers.py` + `tests/server/services/test_push_listener.py` + `tests/server/services/test_reconcile.py` + `tests/server/services/test_t0.py` + `tests/server/services/test_t0_aggregate.py`
- `tests/server/test_layer_dependencies.py`（★ NEW：CI 检查分层依赖方向，含远程 strategy 豁免规则）

**删除文件**（21 个）：
- `server/test_*.py` 全部（commit 后 rm）— 远程 `server/tests/strategy/test_*.py` ×10 **不动**

**修改文件**：
- `pytest.ini` — `testpaths = hq` 保持不变（项目主流跑 `python -m pytest server/` 兼容；`pytest tests/server/` 兜底新路径）

**行为变化**：无（仅测试位置变化）

**验收**：
- [ ] `python -m pytest tests/server/ -v` 全过（21 迁 + 2 新 = 23 个 test 文件）
- [ ] `python -m pytest server/ -v` 报错或部分失败（因为 server/test_*.py 已删；server/tests/strategy/* 远程保留可跑）
- [ ] `pytest tests/server/api/test_orders_api.py -v` monkeypatch 仍可命中 `server.api.orders.ord_stk`
- [ ] `find server -name "test_*.py" -not -path "*/__pycache__/*" -not -path "*/tests/*"` 0 结果（确认顶层 test 全删；strategy 子目录保留）
- [ ] `pytest tests/server/test_layer_dependencies.py -v` 全过（CI 检查 api/ → services/ → repo/ → infra/ 方向合法；远程 strategy 豁免白名单生效）

---

### Commit #6 — `docs(openspec): archive layered-architecture-and-strategy-master（spec 同步 + 归档）`

**修改文件**：
- `openspec/specs/data-model/spec.md` — 改 §1 orders 加 `raw_id` 段（user_def 段保持远程 REQ-TRADE-011 不变；不加 §12 strategy 表，远程 v1 已实现）
- `openspec/specs/trading/spec.md` — REQ-TRADE-003 cancel-row 改第 2 步加 raw_id（user_def 字段不变）；新增 REQ-TRADE-012 cancel-row 双重字段冗余校验
- `openspec/specs/server-architecture/spec.md`（★ NEW spec） — 5 层契约 + 依赖方向规则 + 远程 strategy 豁免规则

**移动目录**：
- `openspec/changes/2026-07-06-layered-architecture-and-strategy-master/` → `openspec/changes/archive/2026-07-06-layered-architecture-and-strategy-master/`

**验收**：
- [ ] `openspec list --type change` 不再含本 change（已 archive）
- [ ] `openspec list --type spec` 含 `server-architecture` 新 spec
- [ ] `grep -r "strategy_type.*=.*Field" openspec/specs/` 0 结果（确认本 change 没引入 strategy_type 字段）
- [ ] `grep -r "raw_id" openspec/specs/` 含 ≥3 命中（data-model + trading + 不含取消）
- [ ] `git log --oneline -6` 顺序符合 plan

---

## 总验收（所有 commit 完成后）

### 后端架构
- [ ] `python -c "import server; from server.api.orders import ord_stk, router; from server.api.strategy import router as strategy_router"` 0 错误（monkeypatch 路径稳定 + 远程 strategy API 不动）
- [ ] `python -c "from server.infra.db import Base, SessionLocal, get_db, db_session, init_db"` 0 错误
- [ ] `python -c "from server.repo.orders import next_order_no, infer_order_status, get_by_order_no, insert_pending_order, insert_cancel_row"` 0 错误
- [ ] `python -c "from server.rpc.transport import RPClient"` 0 错误（继承 MessageQueueClient）
- [ ] `python -c "from server.services.strategy import StrategyEngine, StrategyRepository"` 0 错误（远程 v1 不动）

### DB
- [ ] `sqlite3 server/evtrade.db ".schema orders"` 含 `raw_id`（nullable）
- [ ] 旧 orders 数据无破坏（`SELECT COUNT(*) FROM orders` 与迁移前一致）
- [ ] 旧 cancel-row 数据无破坏（保留 `user_def="CANCEL:..."`，raw_id=NULL）

### 业务功能
- [ ] DELETE /api/orders/{order_no} → cancel-row 双重字段：user_def="CANCEL:{no}" + raw_id={no}
- [ ] POST /api/orders/place → 普通行 raw_id=NULL（user_def 由远程 REQ-TRADE-011 决定）
- [ ] WS `order_update` payload 含 raw_id 字段
- [ ] 远程 strategy API（`/api/strategy/*`）不受影响

### 测试
- [ ] `python -m pytest tests/server/ -v` 全过（23 个 test 文件）
- [ ] `pytest tests/server/api/test_orders_api.py -v` monkeypatch 命中
- [ ] `pytest tests/server/test_layer_dependencies.py -v` 依赖方向检查通过（含远程 strategy 豁免）

### 前端
- [ ] `npm run build` 全过（不动 4 view）
- [ ] `client/src/stores/holdings.js` 透传 raw_id（1-2 行改动）
- [ ] holdings IDB 收到 raw_id 无 schema 报错

### 提交
- [ ] 6 commits 按序列提交（commit message 遵循 `<type>(<scope>): <subject>` 格式）
- [ ] 每个 commit 仅包含其 task 范围文件（避免大杂烩）
- [ ] git push 通过 proxy workaround（`git -c http.proxy=`）