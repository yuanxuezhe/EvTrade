# Restructure Test Layout

## Why

`server/` 当前混杂 **21 个 test_*.py 文件 + 72 个生产源码文件**，导致：

1. **导航困难**：在 `server/api/orders/place.py` 找源码时，旁边就有 `test_orders_api.py`，IDE 目录树噪音大；判断"这是源码还是测试"需要读文件名
2. **pytest 默认不跑**：`pytest.ini` 的 `testpaths = hq` 只指向行情服务；server 测试要靠 `python -m pytest server/ -v` 显式指定，CI / IDE 默认发现不到
3. **历史包袱**：根目录 `conftest.py` 36 行 workaround 解决"裸名 vs 限定名 import 导致 SQLAlchemy Base 重复注册"问题 — 这是测试和生产代码 import 风格不统一的结果；测试移走后自然可消除

frontend (`client/tests/{composables,stores,utils}/`) 已按 `client/src/` 结构镜像，是正确的样板。

## What Changes

### 1. 把 server 测试移出 `server/` 到 `tests/server/`

**目录映射**（mirror `server/` 结构）：

| 当前位置 | 目标位置 |
|---|---|
| `server/test_auth.py` | `tests/server/auth/test_security.py`（按 `server/auth/security.py` mirror） |
| `server/test_config.py` | `tests/server/test_config.py` |
| `server/test_db_session.py` | `tests/server/test_db_session.py` |
| `server/test_format_ts.py` | `tests/server/utils/test_time.py` |
| `server/test_guards.py` | `tests/server/services/test_guards.py` |
| `server/test_holdings_api.py` | `tests/server/api/test_holdings.py` |
| `server/test_logflow.py` | `tests/server/utils/test_logflow.py` |
| `server/test_models.py` | `tests/server/models/test_orm.py` |
| `server/test_order_no.py` | `tests/server/services/test_order_no.py` |
| `server/test_orders_api.py` | `tests/server/api/orders/test_place.py` + `test_cancel.py` + `test_query.py`（按 `server/api/orders/` 子包拆分） |
| `server/test_push_*.py` (4 个) | `tests/server/services/push/test_*.py`（按 `server/services/push/` 子包拆分） |
| `server/test_reconcile.py` | `tests/server/services/test_reconcile.py` |
| `server/test_rpc.py` | **保留位置**（手测脚本，pytest 已 exclude，详见 `pytest.ini`） |
| `server/test_rpc_link.py` | `tests/server/rpc/test_link.py` |
| `server/test_system_api.py` | `tests/server/api/test_system.py` |
| `server/test_t0.py` | `tests/server/services/t0/test_core.py` |
| `server/test_t0_aggregate.py` | `tests/server/api/test_t0_aggregate.py` |
| `server/test_trades_api.py` | `tests/server/api/test_trades.py` |
| `server/test_ws_endpoint.py` | `tests/server/ws/test_endpoint.py`（新建 `server/ws/` 子包？见 §4） |

### 2. 重写 import 风格 + 删除 conftest workaround

测试文件统一用 `from server.X import Y` 限定名（与生产代码一致），不再用 `sys.path.insert(0, 'server/')` + 裸名 import。

**BREAKING**：删除根目录 `conftest.py` 的 SQLAlchemy Base 重复注册 workaround（迁移完成后不再需要）。删除后所有 `test_*.py` 必须改 import 风格。

### 3. 更新 `pytest.ini`

```ini
[pytest]
asyncio_mode = auto
testpaths = hq tests/server    # 新增 tests/server
pythonpath = .                  # 让 `from server.X` 解析
```

### 4. 新建 `server/ws/` 子包（提议）

`server/test_ws_endpoint.py` 测试的是 WS 端点；`server/ws/manager.py` 已存在但端点注册散落在 `server/main.py`。提议把 WS 端点实现也拆出 `server/ws/endpoint.py`，对应测试放 `tests/server/ws/test_endpoint.py`。

**这是提议** — 如果 WS 端点改动太大可推迟，本 change 只移测试。

### 5. 移动运行时数据文件

`server/evtrade.db`（SQLite 数据库文件）混在源码目录。提议移到 `data/evtrade.db`，更新 `server/config.py` 的 DB URL 常量。

### 6. frontend 测试布局文档化（可选）

`client/tests/{composables,stores,utils}/` 已镜像 `client/src/` 结构 — 仅在 `dev-process-control` spec 加一条 scenario 记录"测试镜像源码结构"的约定。当前 4 个测试文件已遵守，不需要改代码。

## Capabilities

### New Capabilities

无新增 capability（纯内部重构，无新对外行为）。

### Modified Capabilities

- `dev-process-control`: 新增 Scenario "测试目录镜像源码结构"（约定：`tests/<layer>/<module>/test_*.py` 镜像 `server/<layer>/<module>.py`，便于 IDE 跳转与 CI 发现）

## Impact

- **新增/移动文件**：21 个 server 测试文件重定位 + 拆分（`test_orders_api.py` 拆 3 个）；新增 `tests/conftest.py`；删除根 `conftest.py`
- **修改文件**：
  - `pytest.ini`：加 `tests/server` + `pythonpath`
  - `server/config.py`：DB URL 从 `sqlite:///./server/evtrade.db` 改 `sqlite:///./data/evtrade.db`
  - `setup.py` / `scripts/evctl.py`（如有 DB 路径引用）
  - 21 个测试文件：import 风格统一改 `from server.X` 限定名
- **可能破坏**：现有 CI 脚本若硬编码 `pytest server/` 路径，需改 `pytest tests/server`
- **不影响**：frontend（已正确）、生产代码逻辑、API 契约、数据库 schema
- **不做**：
  - 不引入新的测试框架（继续 pytest + vitest）
  - 不重构 server 子包结构（api/orders/、services/push/ 已拆分）
  - 不动 `scripts/evctl.py` / `hq/` / `iquant/` / `kb/`

## 不在本 change 范围

- 端点实现位置重整（如 §4 WS 端点拆 `server/ws/endpoint.py`） — 仅提议，可推迟到后续 change
- 测试覆盖率提升（当前目标只是"移动"，不改测试内容）
- CI 配置改动（用户运维范畴）
- 改 `scripts/evctl.py` 的 DB 路径解析（如有需要，独立 change）