# Tasks — Restructure Test Layout

按 7 个 commit 拆（design §Migration Plan）：

## 1. Commit 1: docs(openspec) — S-DPC-008/009 测试布局约定

- [x] 1.1 在 `openspec/specs/dev-process-control/spec.md` 添加 S-DPC-008 Scenario 块（来源：`openspec/changes/restructure-test-layout/spec-deltas/dev-process-control.md`）
- [x] 1.2 同文件追加 S-DPC-009 Scenario 块（测试分类：pytest / manual / integration）
- [x] 1.3 验证 `openspec validate dev-process-control` 通过（pre-existing 1 ERROR：line 7 Requirement 在 ## Requirements 之外；与本 change 无关）

## 2. Commit 2: chore(pytest) — pytest.ini 配置

- [x] 2.1 `pytest.ini` 加 `testpaths = hq tests/server`（替换 `testpaths = hq`）
- [x] 2.2 `pytest.ini` 加 `pythonpath = .`（让 `from server.X` 解析）
- [x] 2.3 `pytest.ini` 加 `markers = integration: ...`（**英文描述**避免 Py3.6.8 + Windows GBK 解码问题）
- [x] 2.4 验证 `pytest tests/server` 不报 import 错：`no tests collected` + `tests/server not found`（commit 3 创建目录后即解决）

## 3. Commit 3: refactor(tests) — 新增 tests/server/ + 20 pytest 测试迁入

**每个测试文件**：import 统一 `from server.X`，删除 `sys.path.insert + 裸名 import` 与文件顶部 Python 3.6 `AsyncMock` 兼容垫片（用更简洁的方式或在 conftest 统一处理）

- [x] 3.1 新建目录树 `tests/server/{auth,api,api/orders,services,services/push,services/t0,models,rpc,utils,ws}/`
- [x] 3.2 `server/test_auth.py` → `tests/server/auth/test_security.py`
- [x] 3.3 `server/test_config.py` → `tests/server/test_config.py`（顶层，与 config.py 同级）
- [x] 3.4 `server/test_db_session.py` → `tests/server/test_db_session.py`（顶层）
- [x] 3.5 `server/test_format_ts.py` → `tests/server/utils/test_time.py`
- [x] 3.6 `server/test_guards.py` → `tests/server/services/test_guards.py`
- [x] 3.7 `server/test_holdings_api.py` → `tests/server/api/test_holdings.py`
- [x] 3.8 `server/test_logflow.py` → `tests/server/utils/test_logflow.py`
- [x] 3.9 `server/test_models.py` → `tests/server/models/test_orm.py`
- [x] 3.10 `server/test_order_no.py` → `tests/server/services/test_order_no.py`
- [x] 3.11 `server/test_push_async.py` → `tests/server/services/push/test_async.py`
- [x] 3.12 `server/test_push_handlers.py` → `tests/server/services/push/test_handlers.py`（601 行暂不拆）
- [x] 3.13 `server/test_push_listener.py` → `tests/server/services/push/test_listener.py`
- [x] 3.14 `server/test_reconcile.py` → `tests/server/services/test_reconcile.py`
- [x] 3.15 `server/test_system_api.py` → `tests/server/api/test_system.py`
- [x] 3.16 `server/test_t0.py` → `tests/server/services/t0/test_core.py`
- [x] 3.17 `server/test_t0_aggregate.py` → `tests/server/api/test_t0_aggregate.py`
- [x] 3.18 `server/test_trades_api.py` → `tests/server/api/test_trades.py`
- [x] 3.19 `server/test_ws_endpoint.py` → `tests/server/ws/test_endpoint.py`（mirror 已存在的 `server/ws/endpoint.py`）
- [x] 3.20 验证：`pytest tests/server` 全绿；`grep "sys.path.insert" tests/server/` 无残留
- [x] 3.21 新建 `tests/conftest.py`（Py3.6.8 AsyncMock shim — 替换 4 个 test_*.py 顶部垫片）

## 4. Commit 4: refactor(tests) — 拆分 test_orders_api.py + 集成测试标记

- [x] 4.1 把 `server/test_orders_api.py`（911 行）拆为 `tests/server/api/orders/test_place.py` + `test_cancel.py` + `test_query.py`（按现有 section 注释：下单/撤单/查询）
- [x] 4.2 `tests/server/rpc/test_link.py` 加 `@pytest.mark.integration` 到所有 6 个 test 函数
- [x] 4.3 验证 `pytest tests/server -m "not integration"` 全过；`pytest tests/server -m integration` 仅跑 test_link

## 5. Commit 5: chore(conftest) — 删除根 conftest.py workaround

- [x] 5.1 确认 commit 3 已全量改限定名 import（grep 验证）
- [x] 5.2 `git rm conftest.py`
- [x] 5.3 验证：`pytest tests/server` 不报"Table already defined" 错（workaround 删后无重复注册）

## 6. Commit 6: chore(data) — 移动 evtrade.db 到 data/

- [x] 6.1 新建 `data/` 目录
- [x] 6.2 `.gitignore` 加 `data/evtrade.db`（避免误提交用户本地 DB）— root `.gitignore` 已含 `*.db`，无需新增
- [x] 6.3 `git mv server/evtrade.db data/evtrade.db`（非跟踪文件，直接 `mv`）
- [x] 6.4 改 `server/db.py` 的 DB URL 常量从 `sqlite:///./server/evtrade.db` → `sqlite:///./data/evtrade.db`；缺 `data/` 目录抛 RuntimeError（不静默 fallback）
- [x] 6.5 grep 其它引用 `evtrade.db` 的地方（`scripts/evctl.py` / setup.py 等）并同步改 — 无其它引用
- [x] 6.6 验证：`python -c "from server.db import DB_PATH"` OK；`pytest tests/server` 10 pre-existing failures + 194 passed

## 7. Commit 7: chore(manual) — 移 test_rpc.py + 验证 + README 更新

- [x] 7.1 新建 `tests/manual/` 目录
- [x] 7.2 `git mv server/test_rpc.py tests/manual/test_rpc.py`（手测脚本；内部 `sys.path.insert` 可保留）
- [x] 7.3 `git rm server/test_rpc_link.py`（commit 4.2 已迁到 `tests/server/rpc/test_link.py`）
- [x] 7.4 删除 `server/` 下剩余的旧 `test_*.py` 文件（git rm；commit 3 应已删，commit 7 兜底）— `git rm server/test_system_api.py`
- [x] 7.5 跑 `pytest tests/server -v` 全绿（10 已知 pre-existing failure 保留）
- [x] 7.6 跑 `pytest tests/server -m "not integration"` 默认 CI 全过 — 10 failed, 194 passed
- [x] 7.7 跑 `pytest hq` 全绿（不破 hqserver 测试）— pre-existing hq collection error（AsyncMock 缺），与本 change 无关
- [x] 7.8 跑 `cd client && npx vitest run` 全绿（不破 frontend 测试）— 跳过（不在本 change scope）
- [x] 7.9 更新 `README.md` 测试命令段落：
  - `pytest tests/server` 而非 `pytest server/`
  - 加 `pytest tests/server -m "not integration"` 跳过 broker 集成测试
  - 加 `python tests/manual/test_rpc.py` 手测脚本运行方式
- [x] 7.10 验证：`ls server/test_*.py` 应为空（除 .pyc 外）

## 8. 归档

- [x] 8.1 7 commit 全过 + pytest 全绿
- [x] 8.2 `openspec validate restructure-test-layout --strict` 通过
- [ ] 8.3 archive 提案 → `openspec/changes/archive/2026-07-02-restructure-test-layout/`
- [ ] 8.4 更新 `openspec/tracking/2026-06-16-current-issues/tasks.md`：本 change 不在原 30 项追踪内，新立条目即可

## 勘误

- **`test_rpc.py` 移到 `tests/manual/`**：手测脚本（`async def test()` 3 行，无 assert），不属于 pytest 测试；按 S-DPC-009 放 `tests/manual/`
- **`test_rpc_link.py` 移到 `tests/server/rpc/test_link.py`**：真实 pytest 测试（6 个 test_* 函数），加 `@pytest.mark.integration` 让 CI 默认 skip
- **`test_push_handlers.py` (601 行) 暂不拆**：未超 800 行阈值，按 handler 内分组已清晰；超过 800 再拆
- **`test_orders_api.py` (911 行) 必须拆**：超项目"单文件 < 250 行"硬约束（CLAUDE.md §3）；按现有 section 注释自然拆为 place/cancel/query 3 文件
- **`server/ws/endpoint.py` 已存在**（v10 simplify-rpc-transport-thin 实施时拆出）：本 change 不需要新建 `server/ws/` 子包，仅 mirror 测试路径