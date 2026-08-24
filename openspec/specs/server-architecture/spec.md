# server-architecture — 后端 5 层模块契约

## Purpose

EvTrade 后端经过 v5-v13 多轮迭代，积累了 100+ Python 文件（`server/` 目录下），按"领域 + 工具 + RPC + API" 4 类混合组织。本 spec 引入**显式 5 层架构**（infra / repo / rpc / services / api），强制单向依赖方向，约束模块边界，使：

- 单文件职责清晰（每层文件 ≤ 250 行 CLAUDE.md 硬约束）
- 跨层修改可预测（依赖方向规则防腐败）
- 新增功能有归属（按业务归属到对应层）
- 测试镜像目录清晰（`tests/<area>/<sub>/` 下，含 server/client/hq 三 area）

**横向分层 vs 纵向业务模块**：本 spec 是横向分层（infra/repo/rpc/services/api）；远程 `2026-07-05-strategy_trade` 的 `services/strategy/` 是纵向业务模块。两者正交。

## 5 层架构

```
api/      ← 服务端接口层（FastAPI routers，前端调用）
services/ ← 业务编排层（跨表 / RPC 组合，跨模块业务流，含 services/strategy/）
rpc/      ← RPC 接口层（消息队列交互，业务级 RPC 调用）
repo/     ← 仓库层（按表聚合的 CRUD，封装 ORM 操作）
infra/    ← 基类层（基础设施抽象，aio_pika / SQLAlchemy 顶层封装）
```

**依赖方向（严格单向，禁止反向 import）**：

```
api/  →  services/  →  repo/  →  infra/  →  tables/
  ↓         ↓            ↓
 ws/     rpc/  ────────┘
```

## Requirements

### REQ-ARCH-001: 5 层模块边界

#### infra/ 基类层
- **包含**：消息队列基类（`MessageQueueClient`）、数据库基类（`DatabaseBase`/`SessionLocal`/`get_db`/`db_session`）
- **职责**：封装第三方依赖（aio_pika / SQLAlchemy）的细节，对上层只暴露纯接口
- **不允许 import**：任何上层（api / services / rpc / repo）；仅可 import `server.tables`（如需要 type hint）和第三方库
- **文件**：当前 ≤ 2 个（`mq.py` + `db.py`）

#### repo/ 仓库层
- **包含**：按表聚合的 CRUD 函数（`repo.orders / repo.trades / repo.positions / repo.assets / repo.system / repo.quote_snapshots`）
- **职责**：封装单表的查询/插入/更新/删除 + 表级业务方法（如 `next_order_no` / `infer_order_status`）；不含跨表编排
- **允许 import**：`server.tables.*` / `server.infra.db` / `server.utils.*`
- **不允许 import**：`server.services.*` / `server.rpc.*` / `server.api.*`
- **文件目标**：每个 `repo/<domain>.py` ≤ 250 行
- **不包含** strategy 表 CRUD（远程 `2026-07-05-strategy_trade` 已实现 `server/services/strategy/repository.py`；本 spec 不动 strategy 模块）

#### rpc/ RPC 接口层
- **包含**：消息队列传输（`RPClient`）+ 业务级 RPC 调用（`handlers.py:qry_*/ord_*/cancel_*`）+ 报文解析（`parsers_*.py`）
- **职责**：通过 MQ 与 broker（xtquant）通信；封装 RPC 调用模式（call / reply / push / dispatch）
- **允许 import**：`server.tables.*` / `server.infra.*` / `server.utils.*` / `server.services.push.*`（push dispatcher）
- **不允许 import**：`server.api.*` / `server.repo.*`
- **继承约束**：`RPClient` MUST 继承 `infra.mq.MessageQueueClient`

#### services/ 业务编排层
- **包含**：跨表 / 跨 RPC 的业务流（`services.t0` / `services.push` / `services.reconcile` / `services.guards` / `services.strategy`）
- **职责**：组合多个 repo 函数 + RPC 调用 + 业务规则（如 T0 配平、对账、push 编排、strategy 信号消费）
- **允许 import**：`server.repo.*` / `server.rpc.*` / `server.tables.*` / `server.infra.*` / `server.utils.*`
- **不允许 import**：`server.api.*`
- **`server/services/strategy/`**：原远程 `2026-07-05-strategy_trade` 的网格引擎子模块（models / repository / indicators / flags / regime / grid / engine / audit）已随 commit `aa70dae` **删除**；现仅含 `signal_consumer`（RabbitMQ 信号 → 下单）+ `quote_consumer`（纯行情快照 + `quote_update` 广播）

#### api/ 服务端接口层
- **包含**：FastAPI routers（`api/orders/` / `api/admin/` / `api/<domain>.py` / `api/script_strategy/`）
- **职责**：暴露 HTTP/WS 端点；调用 services + repo；参数校验（Pydantic）；权限守卫（Depends）
- **允许 import**：所有下层（services / rpc / repo / models / infra / ws / auth / utils / enums / middleware）
- **不允许 import**：无（api 是最外层）
- **`server/api/strategy/`**：原远程 `2026-07-05-strategy_trade` 的网格策略 REST（CRUD + 控制 + 审计查询）已随 commit `aa70dae` **删除**；脚本策略 REST 在 `server/api/script_strategy/endpoints.py`（14 端点，v90）

### REQ-ARCH-002: 单向依赖方向强制

- **强制规则**：每个 Python 文件 `import server.X` 必须满足 `X` 的层 ≤ 当前文件所在层
- **层优先级**（数字越小越内层）：
  - `infra` = 0
  - `tables` = 0（与 infra 同级，纯定义；`server/models/` 已删除，数据访问统一走 `server/tables/`）
  - `repo` = 1
  - `rpc` = 1（与 repo 同级，但 rpc 不依赖 repo；rpc 只依赖 infra）
  - `services` = 2
  - `ws` / `auth` / `middleware` / `utils` / `enums` = 跨层工具，按需 import
  - `api` = 3（最外层）
- **跨同级层规则**：
  - `rpc` 不可 import `repo`（同级且 rpc 在协议层，repo 在数据层）
  - `services` 可同时 import `repo` + `rpc`
- **CI 检查**：`tests/server/test_layer_dependencies.py` 用 `ast` 解析所有 `import server.X` 语句，断言：
  ```python
  LAYER_PRIORITY = {
      "infra": 0, "models": 0,
      "repo": 1, "rpc": 1,
      "services": 2,
      "ws": 2, "auth": 2, "middleware": 2, "utils": 2, "enums": 2,
      "api": 3,
      "main": 3, "db": 0, "config": 0, "constants": 0,  # 兼容垫片
  }
  for src_layer, src_file in enumerate(all_py_files):
      for imported_module in parse_imports(src_file):
          if imported_module starts with "server.":
              target_layer = layer_of(imported_module)
              if LAYER_PRIORITY[target_layer] > LAYER_PRIORITY[src_layer]:
                  # 例外：api/orders/__init__.py 顶层 re-export 允许跨层（兼容 monkeypatch）
                  if src_file.endswith("__init__.py") and "re-export" in file_docstring:
                      continue
                  fail(f"{src_file} imports {imported_module} (forbidden)")
  ```
- **例外**（白名单）：
  - `server/api/orders/__init__.py` — 顶层 re-export 允许跨层（test_orders_api.py monkeypatch 目标）
  - `server/infra/db.py` / `server/main.py` / `server/config.py` / `server/constants.py` — 兼容垫片/入口文件，不做层级检查
  - `server/services/push/*` — push dispatcher 编排层，跨 rpc + repo
  - `server/infra/db.py` — `init_db()` 渲染 `server/schema.yml` → `text()` DDL（不再走 `Base.metadata.create_all`）；表类注册由 `server/tables/metadata.py` 统一负责
  - `server/rpc/transport.py` + `server/rpc/client.py` — RPClient 业务方法编排跨 rpc + repo

### REQ-ARCH-003: 文件行数约束

- **硬约束**：每个源文件 ≤ 250 行（CLAUDE.md）
- **超过处理**：立即拆分为同模块下的子文件（按职责）
- **CI 检查**：`tests/server/test_layer_dependencies.py::test_no_250_line_violation` 用 `wc -l` 检查所有源文件
- **迁移期豁免**：迁移中的 facade 文件（如 `server/infra/db.py` 转兼容垫片）暂不计入（但目标 ≤ 50 行）
- **v120.5 变更（2026-08-10）**：`server/services/strategy/` 网格引擎子模块已随 commit `aa70dae` 删除；现仅存 `signal_consumer` / `quote_consumer`，不再有行数豁免项
- **v13 已知超出**（拆分由后续 PR 处理）：
  - `server/repo/orders.py` (280 行)
  - `server/rpc/transport.py` (380 行)
  - `server/services/t0/aggregators.py` (283 行)
  - `server/api/t0_stats.py` (253 行)

### REQ-ARCH-004: 统一入口规则

- 每个模块目录 MUST 有 `__init__.py` 作为**统一入口**
- 外部模块 MUST 仅从 `__init__.py` 导入暴露的功能
- 禁止"深层路径引入"（如 `from server.services.t0.core import calc_net_amount` → 应改为 `from server.services.t0 import calc_net_amount`）
- **CI 检查**：`grep -r "from server.X.Y.Z import" server/ tests/` 0 结果（除 `__init__.py` 自身）
- **v120.5 变更（2026-08-10）**：`server/services/strategy/` 网格引擎子模块（repository / indicators / flags / regime / grid / engine 等）已随 commit `aa70dae` 删除，deep import 豁免不再需要；现仅存 `signal_consumer` / `quote_consumer`（二者若需豁免应单独评估）

### REQ-ARCH-005: 模块依赖图（文档化）

- **维护位置**：`知识库/后端服务/`（分层结构文档）
- **内容**：
  - 当前 5 层目录树（含每个文件用途 1-2 句）
  - 关键调用链图（place_order / cancel_order / reconcile / push handler / strategy engine 等）
  - 新增功能归属决策树（"X 业务改放进哪层"）
- **更新时机**：每次 PR 涉及层调整时同步更新

### REQ-ARCH-006: 测试目录强制约束

The system SHALL 强制所有测试文件位于 `tests/` 根目录下。

#### 目录布局规则

- **测试 = `tests/<area>/<sub>/test_*`**
- `<area>` ∈ `{server, client, hq}`，与生产代码所在根目录一一对应：
  - `server/` → `tests/server/`
  - `client/` → `tests/client/`
  - `hq/` → `tests/hq/`
- **子目录细化**：当生产代码是 `server/services/strategy/<sub>.py`（子包）时，测试 MUST 落在 `tests/server/services/strategy/<sub>/test_*.py`（按子模块细分）
- **不保留** `tests/<area>/<sub>/__init__.py`（`tests/` 整体不是 Python 包）

#### 禁止的位置

测试文件 MUST NOT 位于以下位置：

- `server/tests/...`（旧 strategy 子包测试位置，commit `1264bf0` 后的孤儿）
- `client/tests/...`（前端 vitest 测试位置，本次迁到 `tests/client/`）
- `hq/test_*.py`（hq 子项目测试位置，本次迁到 `tests/hq/`）
- 任何其他非 `tests/` 根的目录

#### 测试文件识别模式（CI 检查覆盖）

CI 检查 MUST 匹配以下 glob 模式（同时覆盖 pytest + vitest 两侧）：

- `**/test_*.py`
- `**/*_test.py`
- `**/*.test.js`
- `**/*.spec.js`
- `**/*.test.mjs`
- `**/*.spec.mjs`

#### CI 检查（新增到 `tests/server/test_layer_dependencies.py`）

```python
def test_no_tests_outside_tests_root():
    """REQ-ARCH-006: 所有测试文件 MUST 位于 tests/ 根下."""
    import os
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    EXCLUDE_DIRS = {
        "node_modules", "__pycache__", ".vite-cache", ".pytest_cache",
        ".git", "evtrade.egg-info", "dist",
    }
    TEST_GLOBS = [
        "**/test_*.py", "**/*_test.py",
        "**/*.test.js", "**/*.spec.js",
        "**/*.test.mjs", "**/*.spec.mjs",
    ]
    violations = []
    for glob_pattern in TEST_GLOBS:
        for path in repo_root.glob(glob_pattern):
            if any(part in EXCLUDE_DIRS for part in path.parts):
                continue
            rel_str = str(path.relative_to(repo_root)).replace(os.sep, "/")
            if not rel_str.startswith("tests/"):
                violations.append(rel_str)
    assert not violations, (
        "REQ-ARCH-006 violation: test files not under tests/ root:\n"
        + "\n".join(f"  {v}" for v in violations)
    )


def test_no_init_py_in_tests_subdirs():
    """REQ-ARCH-006: tests/ 子目录 SHALL NOT 包含 __init__.py."""
    from pathlib import Path
    repo_root = Path(__file__).resolve().parents[2]
    init_files = list((repo_root / "tests").rglob("__init__.py"))
    assert not init_files, (
        "tests/ subdirs should not have __init__.py:\n"
        + "\n".join(str(p.relative_to(repo_root)) for p in init_files)
    )
```

#### Scenario: 策略测试目录（v120.5 网格引擎测试已删）

> **变更说明（2026-08-10）**：网格引擎测试（`server/tests/strategy` + `tests/server/services/strategy`）已随 commit `aa70dae` 删除。

- **WHEN** 开发者为 `server/services/strategy/signal_consumer.py` 写测试
- **THEN** 测试 MUST 在 `tests/server/services/strategy/signal_consumer/test_signal_consumer.py`
- **AND** NOT 在 `server/tests/strategy/` 或其他位置

#### Scenario: 前端测试迁到 tests/client/

- **WHEN** 开发者为 `client/src/composables/useT0Stats.js` 写测试
- **THEN** 测试 MUST 在 `tests/client/composables/useT0Stats.test.js`
- **AND** NOT 在 `client/tests/composables/useT0Stats.test.js` 或其他位置

#### Scenario: hq 测试迁到 tests/hq/

- **WHEN** hq 子项目新增测试
- **THEN** 测试 MUST 在 `tests/hq/test_<name>.py`
- **AND** NOT 在 `hq/test_<name>.py` 或其他位置

#### Scenario: CI 拦截违规

- **WHEN** 开发者误在 `server/tests/foo/test_foo.py` 新建文件
- **THEN** `pytest tests/server/test_layer_dependencies.py::test_no_tests_outside_tests_root` fail
- **AND** 输出 `REQ-ARCH-006 违规：测试文件不在 tests/ 根下：server/tests/foo/test_foo.py`
- **修复**：用 `git mv` 迁到 `tests/server/<layer>/foo/test_foo.py`

#### Scenario: 误建 __init__.py 被拦截

- **WHEN** 开发者误建 `tests/server/services/strategy/__init__.py`
- **THEN** `pytest tests/server/test_layer_dependencies.py::test_no_init_py_in_tests_subdirs` fail
- **修复**：`rm tests/server/services/strategy/__init__.py`

## Scenario: 分层违规被 CI 拦下

- **WHEN** 开发者新增 `server/repo/orders.py` 中的 import 段：`from server.api.orders import router`
- **THEN** `pytest tests/server/test_layer_dependencies.py` 报错：`server/repo/orders.py imports server.api.orders (forbidden: layer 1 → layer 3)`
- **修复**：repo 不应反向 import api；如确需 router 实例化，应通过 DI 注入或挪到 services 层

## Scenario: 文件超 250 行被 CI 拦下

- **WHEN** `server/services/push/dispatcher.py` 增长到 280 行
- **THEN** `pytest tests/server/test_layer_dependencies.py` 报错：`server/services/push/dispatcher.py: 280 lines (>250)`
- **修复**：按职责拆分为 `dispatcher_main.py` + `dispatcher_routes.py` + `dispatcher_trd.py` 等

## Scenario: monkeypatch 路径稳定

- **WHEN** 测试用 `monkeypatch.setattr("server.api.orders.ord_stk", mock)`
- **THEN** 路径 MUST 命中（即便 `ord_stk` 实际定义在 `server/rpc/handlers.py`，`server/api/orders/__init__.py` 顶层 re-export 必须保留 `ord_stk` 名字）

## Scenario: strategy 子模块不再豁免

> **变更说明（2026-08-10）**：网格引擎子模块（engine / indicators / regime / grid 等）已随 commit `aa70dae` 删除，远程豁免不再适用。

- **WHEN** 开发者为 `server/services/strategy/signal_consumer.py` / `quote_consumer.py` 新增跨层 import
- **THEN** 路径必须符合 REQ-ARCH-004（走 `__init__.py` 统一入口），无远程豁免
- **后续工作**：不适用（豁免已随网格引擎删除撤销）

## 不在本 spec 范围

- ❌ 跨层重构的**具体实施计划**（见 `changes/2026-07-06-layered-architecture-and-strategy-master/tasks.md`，已 archive）
- ❌ 每个 repo 函数的**具体实现**（见 `data-model/spec.md` §N 字段约束 + `trading/spec.md` REQ-TRADE-NNN 业务约束）
- ❌ 第三方库（aio_pika / SQLAlchemy）的 API 契约（见各自官方文档）
- ❌ ~~远程 `services/strategy/` 子模块的 deep import 收敛~~（2026-08-10 网格引擎子模块已删，豁免撤销；`signal_consumer` / `quote_consumer` 若有豁免需单独评估）

## v129 add-stkpool-module — 证券池 REST 契约

> **变更说明（2026-08-16）**：新增 `server/api/stkpool.py` 提供 7 个 REST 端点（4 主表 + 2 明细 + 1 明细查询），主表全局共享、走统一 `auth` 鉴权、无 RBAC 角色分层。

### REQ-STKPOOL-API-001: 7 端点契约

#### 主表端点

| 方法 | 路径 | 说明 | 鉴权 |
|---|---|---|---|
| `GET` | `/api/stkpool` | 全量主表，按 `id ASC` | auth |
| `POST` | `/api/stkpool` | 创建池（body: `name`, `remark?`） | auth |
| `PUT` | `/api/stkpool/{pool_id}` | 改池名/备注（body: `name?`, `remark?`） | auth |
| `DELETE` | `/api/stkpool/{pool_id}` | 删池（CASCADE 自动清明细） | auth |

#### 明细端点

| 方法 | 路径 | 说明 | 鉴权 |
|---|---|---|---|
| `GET` | `/api/stkpool/{pool_id}/detail` | 池明细列表，按 `stock_code ASC` | auth |
| `POST` | `/api/stkpool/{pool_id}/detail` | 加明细（body: `stock_codes`，逗号分隔批量） | auth |
| `DELETE` | `/api/stkpool/{pool_id}/detail/{stock_code}` | 删明细 | auth |

**鉴权规则**：

- 全部端点 MUST 走 `auth` 鉴权（任何合法登录用户）
- MUST NOT 再分 RBAC 角色（不强制 admin）
- 鉴权依赖位于 `server/api/deps.py` 现有 `get_current_user` 依赖

**路由注册**：

- `server/main.py` MUST 追加 `app.include_router(stkpool.router)`（router 内部已声明 `prefix="/api/stkpool"`）
- 放在 `script_strategy` 或 `admin` 路由附近（按主题分组）

#### Scenario: 主表 GET 全量

- **WHEN** `GET /api/stkpool` 收到鉴权合法请求
- **THEN** 后端 `StkpoolRepo.list_pools()` → `Stkpool.query_all('asc')`
- **AND** 返回 200 `{pools: [{id, name, remark, created_at}, ...]}`
- **AND** 按 `id ASC` 排序
- **AND** 鉴权失败（无 token / 过期）→ 401

#### Scenario: 主表 POST 创建

- **WHEN** `POST /api/stkpool {"name": "白马", "remark": "高股息"}` 收到
- **THEN** Pydantic `StkpoolCreate` 校验：`name` 长度 1-64, `remark` ≤ 255
- **AND** `StkpoolRepo.create_pool(name, remark)` 查重 + `upsert_one`
- **AND** 成功 → 201 + Row `{id, name, remark, created_at}`
- **AND** name 重复 → 409 `POOL_NAME_DUPLICATE`
- **AND** name 缺/空 → 422 `VALIDATION_ERROR`

#### Scenario: 主表 PUT 改

- **WHEN** `PUT /api/stkpool/5 {"name": "白马 (改)"}` 收到
- **THEN** Pydantic `StkpoolUpdate` 校验（partial update）
- **AND** `StkpoolRepo.update_pool(5, name=..., remark=...)` → `Stkpool.update_one({'name':...}, id=5)`
- **AND** 成功 → 200 + Row
- **AND** 池不存在 → 404 `POOL_NOT_FOUND`

#### Scenario: 主表 DELETE 删池

- **WHEN** `DELETE /api/stkpool/5` 收到
- **THEN** `StkpoolRepo.delete_pool(5)` → `Stkpool.delete_one(id=5)`
- **AND** MySQL FK CASCADE 自动清除 `stkpooldetail.id=5`
- **AND** 成功 → 204 No Content
- **AND** 池不存在 → 404 `POOL_NOT_FOUND`（rowcount=0）

#### Scenario: 明细 GET 列表

- **WHEN** `GET /api/stkpool/5/detail` 收到
- **THEN** `StkpoolRepo.list_detail(5)` → `StkpoolDetail.query_by('id', 5, order='asc')`
- **AND** 返回 200 `{details: [{id, stock_code}, ...]}` 按 `stock_code ASC`
- **AND** 池不存在 → 404 `POOL_NOT_FOUND`（先查池）

#### Scenario: 明细 POST 加（v128 批量）

- **WHEN** `POST /api/stkpool/5/detail {"stock_codes": "600519.SH,000001.SZ,600030.SH"}` 收到
- **THEN** Pydantic `StkpoolDetailAdd` 校验 `stock_codes` 非空 + 长度 ≤ 8192
- **AND** 后端按 `,` split + strip + 去空 → 候选 codes 列表
- **AND** 校验每条匹配 `^\d{6}\.(SH|SZ|BJ)$`，否则 422 `VALIDATION_ERROR: invalid stock_codes: [...]`
- **AND** 候选 codes 去重（防御性）
- **AND** `StkpoolRepo.add_detail_batch(5, codes)` → 单事务 `INSERT IGNORE INTO stkpooldetail (id, stock_code) VALUES ...`
- **AND** 返回 201 + `{pool_id: 5, added: N, skipped: M}` (added = rowcount, skipped = 总数 - added)
- **AND** 重复 → skipped > 0（幂等）
- **AND** 池不存在 → 404 `POOL_NOT_FOUND`
- **AND** split 后为空 → 422 `VALIDATION_ERROR: stock_codes cannot be empty after split`

#### Scenario: 单只兼容（向后兼容）

- **WHEN** `POST /api/stkpool/5/detail {"stock_codes": "600519.SH"}` 收到（只 1 只）
- **THEN** split 后 codes = ["600519.SH"]
- **AND** 走同一 `add_detail_batch` 路径
- **AND** 返回 201 + `{pool_id: 5, added: 1, skipped: 0}`

#### Scenario: 明细 DELETE 删

- **WHEN** `DELETE /api/stkpool/5/detail/600519.SH` 收到
- **THEN** `StkpoolRepo.remove_detail(5, '600519.SH')` → `StkpoolDetail.delete_one(id=5, stock_code='600519.SH')`
- **AND** 成功 → 204
- **AND** 不存在 → 404 `DETAIL_NOT_FOUND`

### REQ-STKPOOL-API-002: 错误码契约

The system SHALL 使用统一的错误码格式 `{detail: "<CODE>: <human readable message>"}`，与现有 `asset-position-adjust` 模块对齐。

| 错误码 | HTTP | 触发场景 |
|---|---|---|
| `POOL_NOT_FOUND` | 404 | 池不存在 |
| `DETAIL_NOT_FOUND` | 404 | 明细不存在 |
| `POOL_NAME_DUPLICATE` | 409 | name 重复 |
| `VALIDATION_ERROR` | 422 | Pydantic 入参校验失败 |
| `INTERNAL_ERROR` | 500 | DB 异常 |

**实现位置**：

- 业务异常类（`PoolNotFound`, `PoolNameDuplicate`, `DetailNotFound`）定义在 `server/api/stkpool.py` 内部
- 路由处理器通过 `try/except` 捕获 → 转 `HTTPException(status_code, detail)`

#### Scenario: 错误码格式统一

- **WHEN** 任何 stkpool 端点遇到业务错误
- **THEN** 响应 `detail` 字段 MUST 格式为 `<CODE>: <message>`
- **AND** 状态码 MUST 匹配上表

#### Scenario: VALIDATION_ERROR 由 Pydantic 自动生成

- **WHEN** `POST /api/stkpool {"name": ""}` 收到（name 空）
- **THEN** Pydantic FastAPI 自动生成 422 + `detail: [{loc: ["body", "name"], msg: "ensure this value has at least 1 characters", ...}]`
- **AND** MUST NOT 走到 Repo 业务层

### REQ-STKPOOL-API-003: 鉴权边界

The system SHALL 对所有 7 个 stkpool 端点统一鉴权，无 RBAC 角色分层。

#### Scenario: 已登录用户可访问

- **WHEN** 合法 JWT 携带 `Authorization: Bearer ...`
- **THEN** 端点正常处理，返回 200/201/204

#### Scenario: 未登录返回 401

- **WHEN** 无 token / token 过期 / token 解析失败
- **THEN** FastAPI 鉴权依赖返回 401
- **AND** 端点代码 MUST NOT 走到 Repo

#### Scenario: 普通用户与 admin 都有权限

- **WHEN** 普通用户 (`role: 'trader'`) 调 `POST /api/stkpool`
- **THEN** 入口鉴权通过 → 业务正常处理
- **WHEN** admin 调同一端点
- **THEN** 行为完全一致（无 RBAC 差异）

### REQ-STKPOOL-API-004: Pydantic Schema 命名规范

The system SHALL 在 `server/api/stkpool.py` 同文件内定义 Pydantic 模型，命名遵循 `Stkpool<Verb>` 模式：

```python
class StkpoolCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    remark: str = Field(default='', max_length=255)

class StkpoolUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    remark: str | None = Field(default=None, max_length=255)

class StkpoolDetailAdd(BaseModel):
    """v128: 批量接口 — stock_codes 用逗号分隔多只股票"""
    stock_codes: str = Field(min_length=1, max_length=8192)
```

#### Scenario: Schema 字段定义

- **WHEN** 任何端点接到 body
- **THEN** FastAPI 自动 Pydantic 校验
- **AND** 失败 → 422 `VALIDATION_ERROR`
- **AND** 成功 → 进入业务层

#### Scenario: 路由清单注册后启动验证

- **WHEN** `uvicorn server.main:app --reload` 启动
- **THEN** `curl http://localhost:8000/api/stkpool` 返 200 + `{pools: []}`
- **AND** 端点需带鉴权头（无 token 返 401）

### REQ-ARCH-008: Hermes Agent Client + WS Gateway + Confirmation 协议 (2026-08-23, upgrade-agent-to-v1-runs change)

> 详见 change `openspec/changes/2026-08-23-upgrade-agent-to-v1-runs/`（取代 `ai-agent-panel` + `ai-agent-ws-reuse-channel` 的 JSON-RPC over WS 方案）。本节为现行契约。

#### Purpose

EvTrade FastAPI 作为**薄包装网关**调用 Hermes 自带的 API server（`/v1/runs` 异步端点 + SSE 事件流），把 WS `agent_channel` 收到的用户消息转 REST 调用，再把 SSE 事件透传回 WS。完全删除自研 JSON-RPC over WS 协议。

#### 客户端契约

- **文件**：`server/services/agent/hermes_serve_client.py`（REST + SSE 客户端，httpx async）
- **基础 URL**：`HERMES_API_BASE_URL`（默认 `http://127.0.0.1:8642`）
- **鉴权**：`Authorization: Bearer ${HERMES_API_KEY}`（`HERMES_API_KEY` = `~/.hermes/.env` 的 `API_SERVER_KEY`）
- **接口**：
  - `submit_run(input: str, session_id: str, instructions: str | None = None, conversation_history: list | None = None) -> str` → 返回 `run_id`（POST `/v1/runs`）
  - `stream_events(run_id: str) -> AsyncIterator[HermesEvent]`（GET `/v1/runs/{run_id}/events`，SSE 逐行解析 `data:` JSON）
  - `respond_approval(run_id: str, choice: str, resolve_all: bool = False) -> None`（POST `/v1/runs/{run_id}/approval`，`choice ∈ {once, session, always, deny}`）
  - `stop_run(run_id: str) -> None`（POST `/v1/runs/{run_id}/stop`）
  - `get_run_status(run_id: str) -> dict`（GET `/v1/runs/{run_id}`）
  - `is_reachable() -> bool`：GET `{HERMES_API_BASE_URL}/` 任意 HTTP 响应即视为可达（沿用 `2026-08-23-fix-agent-is-reachable-healthz` 判据）
- **超时**：HTTP 请求默认 30s；SSE 流式订阅无超时（由 client 主动 close）
- **错误**：HTTP 5xx → raise `HermesError`；4xx → raise `HermesError`；网络错误 → raise `HermesUnreachableError`

#### SSE 事件类型（由 Hermes API server 推送）

| 事件 | 含义 |
|---|---|
| `run.started` | run 开始（含原始用户消息） |
| `message.started` | LLM 开始响应 |
| `tool.progress` | 推理/工具进度（`tool_name` + `delta`） |
| `tool.started` | tool 调用开始（`tool_name` + `args` + `preview`） |
| `tool.completed` | tool 返回结果（`result`） |
| `tool.failed` | tool 失败（`error`） |
| `assistant.completed` | LLM 文本段生成完成（`content`） |
| `run.completed` | run 结束（`usage`） |
| `approval.required` | 高危 tool 等用户确认（`pending_key` + `tool_name` + `args`） |
| `error` | 错误 |
| `done` | 流结束标记 |

#### WS Gateway 契约

- **文件**：`server/ws/endpoint.py`（复用现有 `/ws/{channel}` handler，agent_channel 分支薄包装）
- **端点**：`WS /ws/agent_channel`（与 `/ws/quote_update` 等共用同一 endpoint）
- **薄包装职责**：
  1. 接 `{type: "user_message", text, session_id?}` → 调 `submit_run` → 订阅 `stream_events` → 推 SSE 事件给前端
  2. 接 `{type: "confirmation", run_id, pending_key, choice}` → 调 `respond_approval`
  3. 接 `{type: "stop", run_id}` → 调 `stop_run`
  4. SSE 事件 → WS 消息透传（`{type: <event_name>, ...event_fields}`，WS handler 注入 `run_id`）
- **移除**：`ConfirmRegistry` 拦截逻辑（Hermes API server 自身处理 approval）
- **复用**：JWT 鉴权、idle timeout、ping/pong 不变

#### 沙箱边界

- JWT 由 FastAPI 解，user_id 注入下游 MCP tool 调用（已有，`_jwt.py` 函数式读 JWT_SECRET）
- Hermes API server 调用 MCP 时，MCP tool 强制从 JWT 拿 user_id，LLM **不得**覆盖
- 高危 tool（`place_order`/`cancel_order`/`delete_strategy_script`/`set_user_role`/`init_trading_day`）由 Hermes API server 在 `tools/approval.py` 拦截，EvTrade FastAPI 不再二次实现

#### Scenario: 端到端对话

- **GIVEN** Vue 连 `/ws/agent_channel?token=<jwt>` → Hermes API server `:8642` 已启 + MCP 9 tool 已注册
- **WHEN** Vue 发 `{type: "user_message", text: "查一下当前持仓"}`
- **THEN** FastAPI 调 `submit_run` → 拿 `run_id` → 订阅 SSE
- **AND** FastAPI 推 WS `{type: "run.started", run_id, session_id}`
- **WHEN** Hermes 决定调 `list_positions` tool
- **THEN** FastAPI 推 WS `{type: "tool.started", tool_name: "list_positions", args: {}}`
- **AND** tool 返回持仓 → FastAPI 推 WS `{type: "tool.completed", result: ...}`
- **WHEN** LLM 生成文本
- **THEN** FastAPI 推 WS `{type: "assistant.completed", content: "您当前持仓..."}`
- **AND** 推 WS `{type: "run.completed", ...}`

#### Scenario: 高危 tool 二次确认

- **GIVEN** 用户发"帮我下单 100 股 600000.SH"
- **WHEN** Hermes 决定调 `place_order` tool + API server 拦截
- **THEN** Hermes 在 SSE 流推 `approval.required` 事件（字段含 `pending_key`, `tool_name`, `args`）
- **AND** FastAPI 透传为 WS `{type: "approval.required", pending_key, tool_name, args}`
- **WHEN** 用户在 Vue Confirm Modal 确认
- **THEN** Vue 发 `{type: "confirmation", run_id, pending_key, choice: "once"}`
- **AND** FastAPI 调 `respond_approval(run_id, "once")` → Hermes 继续执行 tool
- **AND** 推 WS `{type: "tool.completed", result: {order_no: "..."}}`

#### 端口复用原则（不变）

- FastAPI 8000 端口同时承载 `/api/*` HTTP + `/ws/{channel}` WS（包括 agent_channel）
- Hermes API server :8642 独立进程，由 Hermes gateway 启动时 spawn
- MCP 9 tool 在 Hermes API server 进程内 spawn（由 `tools/approval.py` 拦截）
- **0 新端口**

#### 移除清单（2026-08-23 完成）

- ✗ `server/api/agent.py`（旧独立 `/api/agent/ws` endpoint，已删）
- ✗ `server/services/agent/agent_confirm.py`（ConfirmRegistry，新版不再需要）
- ✗ `server/tests/services/agent/test_agent_confirm.py`（同上）

#### 配置变更

| 旧 | 新 |
|---|---|
| `HERMES_SERVE_WS_URL=ws://127.0.0.1:9119/ws` | `HERMES_API_BASE_URL=http://127.0.0.1:8642` |
| （hermes serve 自己读 .env） | `HERMES_API_KEY=<API_SERVER_KEY>` |
| evctl 默认启 hermes serve :9119 | evctl **不**启 hermes serve（Hermes gateway api_server platform 内置） |

#### Scenario: WS 端口复用

- **GIVEN** FastAPI 服务监听 8000 端口，注册 `/ws/{channel}` endpoint
- **WHEN** 用户 WS 连接 `ws://host:8000/ws/quote_update?token=...`（行情订阅）
- **AND** 用户 WS 连接 `ws://host:8000/ws/agent_channel?token=...`（AI 对话）
- **THEN** 两个 WS 共存，由 `_resolve_ws_user` 统一鉴权 + `ws_manager` 按 channel key 分别跟踪
- **AND** 任一连接 idle 超时都触发独立 close 4001
- **AND** 互不干扰

#### MCP Server 契约

- **文件**：`server/mcp/evtrade_mcp_server.py`（FastMCP 入口）
- **端口**：`EVMCP_PORT=8787`（独立 daemon）
- **Tool 列表**：12 个（详见 `openspec/changes/2026-08-23-ai-agent-panel/proposal.md` §12 tool 候选清单）
- **JWT 注入**：每个 tool 必须接收 `jwt_token: str` 参数 → 服务端校验 → 用 user_id 调下游 EvTrade REST API
- **高危 tool**：`place_order` / `cancel_order` / `delete_strategy_script` / `set_user_role` / `init_trading_day` — 不直接执行，返回 `{"status": "confirmation_required"}`，由 FastAPI gateway 拦截并推给前端确认
- **启动方式**：FastAPI 启动时 spawn 子进程（用 `subprocess.Popen`），FastAPI 退出时 kill

#### 二次确认协议

- FastAPI 维护 `pending_confirmations: dict[run_id, asyncio.Future[bool]]`
- 拦截 MCP tool call（白名单）→ 不调 MCP → 推 WS `confirmation_required` → 等 Future（60s 超时）
- 用户在 Vue Modal 确认 → FastAPI 解析 Future → 调 MCP tool（这次真执行）→ 继续 hermes run
- 超时 / 用户拒绝 → Future cancel + 返回 `{"status": "user_rejected"}` 给 hermes → LLM 整合自然语言响应

#### 沙箱边界

- LLM **不得**指定 user_id（所有 tool 的 user_id 从 JWT 强制注入）
- LLM **不得**看到其他用户的资源（tool 返回结果只含当前 user 的数据）
- LLM **不得**写 EvTrade 任意文件（tool 只能调预定义 REST API）
- 高危 tool **必须**经前端二次确认

#### Scenario: WS JWT 校验

- **WHEN** Vue WS 连接 `ws://host/ws/agent_channel?token=<invalid_jwt>`
- **THEN** FastAPI 关闭连接 + code 1008（policy violation）
- **AND** 不创建 session

#### Scenario: 高危 tool 二次确认流程

- **GIVEN** user 通过 WS 发送 "帮我下单 100 股 600000.SH"
- **WHEN** Hermes agent 决定调 `place_order` tool
- **THEN** FastAPI gateway 拦截（白名单命中）
- **AND** 推 WS `confirmation_required` 事件（含 place_order params 预览）
- **WHEN** Vue Modal 用户点 "确认"
- **THEN** Vue 发 `{type: "confirmation", confirmed: true}`
- **AND** FastAPI 调 MCP tool 真正执行下单
- **WHEN** 60s 内无响应
- **THEN** Future cancel → 推 WS `error: confirmation_timeout`
- **AND** LLM 整合 "user did not respond in time" 自然语言响应

#### Scenario: LLM 越权尝试

- **GIVEN** LLM 在 tool call 时试图指定 `user_id="other_user"`
- **WHEN** MCP tool 收到请求
- **THEN** tool **必须**忽略 LLM 传入的 user_id
- **AND** tool **必须**用 JWT 解出的 user_id 调下游 API
- **AND** tool 返回的 result **不得**包含其他 user 的数据
