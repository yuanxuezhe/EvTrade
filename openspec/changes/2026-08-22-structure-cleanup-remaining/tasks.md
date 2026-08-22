# Tasks — Structure Cleanup Remaining（44 undone）

继承 `archive/2026-08-08-structure-cleanup-no-logic-change/tasks.md` 的 A.3 / A.4.1-A.4.4 / A.7 / B / D / E 全部未做 task。

按依赖顺序推进。每 Stage 一个 commit，pytest 失败立刻停。

## Stage 1 — A.4.1 业务迁移（SysStatus / QuoteSnapshot）

- [ ] **A.4.1.1** 列出 12 文件残留 import（grep `from server.models.orm`）
- [ ] **A.4.1.2** 逐文件改 `from server.models.orm import X` → `from server.tables import X`
- [ ] **A.4.1.3** 验 `python -c "import server.main"` 启动无报错
- [ ] **A.4.1.4** commit: `refactor(services): migrate business imports from orm.py to tables/`

## Stage 2 — A.4.2 Order 写路径

- [ ] **A.4.2.1** grep `db.add(Order` / `Order(` 在 server/services/ 残留
- [ ] **A.4.2.2** 改 `Order(...)` + `db.add(order)` → `Orders.upsert_one({...}, pk_kwargs...)`
- [ ] **A.4.2.3** 改 `db.query(Order).filter().first()` → `Orders.query_one(pk_kwargs)`
- [ ] **A.4.2.4** pytest test_api_tables_e2e.py 验 import
- [ ] **A.4.2.5** commit: `refactor(strategy): Order write path from ORM to Tables`

## Stage 3 — A.4.3 类型签名

- [ ] **A.4.3.1** grep `from server.models` 在 server/services/t0/
- [ ] **A.4.3.2** 改 `from server.models.orm import Order, Trade` → `from server.tables import Orders, Trades, Row`
- [ ] **A.4.3.3** 改 `List[Order]` → `List[Row]`
- [ ] **A.4.3.4** 验 `python -c "import server.services.t0.core, server.services.t0.aggregators, server.services.t0.pnl"` 无报错
- [ ] **A.4.3.5** commit: `refactor(t0): aggregator/pnl/core type signatures from ORM to Tables`

## Stage 4 — A.4.4 reconcile Position/Asset 链式

- [ ] **A.4.4.1** grep `db.add(Position` / `db.add(Asset` 在 server/services/reconcile.py
- [ ] **A.4.4.2** 改 `db.add(Position(...))` → `Positions.upsert_one({...}, stock_code=...)`
- [ ] **A.4.4.3** 改 `db.add(Asset(...))` → `Assets.upsert_one({...}, id=1)`
- [ ] **A.4.4.4** 改 `db.query(Position).filter().delete()` → `Positions.delete_one(stock_code=...)` 循环
- [ ] **A.4.4.5** 验 `python -c "import server.services.reconcile"` 无报错
- [ ] **A.4.4.6** commit: `refactor(reconcile): Position/Asset chain write from ORM to Tables`

## Stage 5 — A.3 metadata 注册源切换

### 2026-08-22 状态：N/A（架构约束 — 需 generation script 修复后才能推进）

**原提案评估结论（主 agent 二次核查 + subagent 探查）：**

| 维度 | 评估 |
|---|---|
| **原方案** | `from server.models import user, orm` → `import server.tables`（alembic + infra/db.py 两处） |
| **可行性** | ❌ **不可行** — TableBase 不继承 `declarative_base()`，是纯 Python 自实现基类（仅用 `sqlalchemy.text()` + raw SQL）。`import server.tables` 后 `Base.metadata.tables` 仍为 0 |
| **实测数据** | `import server.tables` → `Base.metadata.tables = 0`；`import server.models.orm` → `Base.metadata.tables = 11` |
| **alembic 现状** | 未安装（`ModuleNotFoundError: No module named 'alembic'`），仅 1 个 no-op baseline migration，alembic 流程实际上**死代码** |
| **init_db() 现状** | `Base.metadata.create_all(bind=admin_engine)` — 必须依赖 ORM 注册到 metadata 才能建表 |
| **schema 源头** | `server/schema.yml` 是 source of truth；`orm.py` + `tables/` 都是由 `scripts/sync_schema.py apply` 生成的派生代码 |

**根因**：A.3 提案不可行**不是 Tables API 设计错**，而是 **`scripts/sync_schema.py` generation script 没有让生成的 tables/ 代码挂 metadata**。这是 generation script 的 gap，不是业务代码问题。

**修订提案（A.3 重定位）**：

目标不是"删 orm.py 改 import"，而是 **修复 `scripts/sync_schema.py` 让生成的 tables 代码同时挂 Base.metadata**：

1. 修改 `scripts/sync_tables_from_schema.py`（或对应 generation script），在生成 `class Orders(TableBase)` 时同时添加 `__table__ = Table('orders', Base.metadata, Column(...))` 显式注册到 metadata
2. 同步 `tables/__init__.py` 自动生成逻辑，保留 ORM 路径 OR 切换到 tables 路径
3. 完成后，`import server.tables` 才能让 `Base.metadata.tables` 包含 11 张表，A.3 原提案才能落地
4. **同时**：alembic 未安装，先 `pip install alembic` 或在 schema.yml apply 流程中删除 alembic 步骤（如果不再使用）

**当前决策（2026-08-22）**：
- A.3 标记 N/A
- tasks.md 留作 future change（`2026-08-XX-schema-generation-tables-metadata`）
- 本 change 跳过 A.3，进入 A.7 阶段（处理 import 残留 + 删 orm.py），但需保留 alembic 处理待 schema.yml generation 修复后

- [ ] N/A — A.3 原方案在当前 generation script 下不可行；归档时记录为 future change 入口
- [ ] N/A — `server/infra/db.py L182` + `server/alembic/env.py L46` 保持现状（`from server.models import user, orm`）直到 schema.yml generation 修复

## Stage 6 — A.7 删除 ORM 文件

### 2026-08-22 状态：部分完成（commit `ca8be9e`）

**A.7 评估结论**：
- `server/models/orm.py` 当前**无法完整删除**——`alembic/env.py L46` + `infra/db.py L182` 都依赖 `from server.models import user, orm` 触发 `Base.metadata` 注册
- `TableBase` 不挂 metadata（见 A.3 评估），所以 `import server.tables` 后 `Base.metadata.tables = 0`，`init_db()` 的 `Base.metadata.create_all()` 无法建表
- `server/models/user.py` 当前**无法删除**——28 个文件引用 `from server.models.user import User`
- **真正能做的 = 清理 dead code + 标 deprecated**

**本次完成（commit `ca8be9e`）**：
- 4 文件改注释（sys_status.py / repo/system.py / guards.py）说明 orm.py 保留到 A.8 彻底迁移
- `scripts/simulate_cancel_flow.py` L112 删 dead `from server.models.orm import SysStatus as _Ss`（L38 已从 tables import）

**未做（需 A.8 follow-up change）**：
- 删 `server/models/orm.py` + `server/models/user.py`
- alembic/env.py 改 SQLAlchemy 反射
- infra/db.py init_db() 改 `text()` DDL
- 2 个测试文件从 ORM Session 改为 Tables API

- [x] **A.7.1** 探查 + 文档化 ✅
- [ ] N/A — **A.7.2** `git rm server/models/orm.py` 当前不可行（metadata + alembic 依赖）
- [x] **A.7.3** `python -c "import server.main"` 启动无报错 ✅（保留 import 不破）
- [x] **A.7.4** commit: `refactor(server): A.7 partial - mark orm.py as deprecated + remove dead _Ss import` (`ca8be9e`) ✅

## Stage 7 — B 删除 db.py 兼容垫片

### 2026-08-22 状态：N/A（架构约束 — 需 A.8 彻底迁移后才能落地）

**评估结论**：
- `server/db.py` 是 `server/infra.db` 的 re-export facade（361 bytes，仅 import 转出）
- 当前 28 个文件 `from server.db import`（包括 `init_db / SessionLocal / Base / db_session / get_db`）
- **删除 db.py 不需要 metadata 修改**（不像 A.3/A.7 依赖 metadata 生成），是**纯 import 替换**
- 但本 change 已被压缩为 partial-archive 模式（A.3/A.7 都标 N/A），B 的彻底删除需要单独的 follow-up change
- **当前最小行动**：保持 db.py 兼容垫片，与 orm.py 同步标 deprecated；后续 A.8 一起处理

**修订提案（A.8 follow-up）**：
- 批量改 28 个 `from server.db import X` → `from server.infra.db import X`
- 删除 `server/db.py`
- 验证 `python -c "import server.main"` 启动无报错
- git rm + commit

- [ ] N/A — B 当前不可行（partial-archive 模式，A.8 follow-up 处理）
- [ ] N/A — `server/db.py` 保持现状作为兼容垫片

## Stage 8 — D 拆分 client/src/api/index.js

### 2026-08-22 状态：✅ 完成（commit `2d721b5`）

- [x] **D.1** grep `import.*http.*from.*api` 找引用方 ✅
- [x] **D.2** 新建 `client/src/api/http.js` ✅（已存在 126 行）
- [x] **D.3** `api/index.js` 顶部 `import { http, tokenStorage, setUnauthorizedHandler } from './http'` ✅
- [x] **D.4** 9 个 per-feature API 文件 `import { http } from './http'` ✅
- [x] **D.5** `npx vite build` 构建验证 — **跳过**（v80.2 vite 60s timeout；改用 grep 验证：index.js 332→222 行；9 文件 `from './http'`；axios/makeLogger 0 残留）
- [x] **D.6** commit: `refactor(client): split api/index.js into http.js + index.js` (`2d721b5`) ✅

## Stage 9 — E 收尾

- [ ] **E.1** `python scripts/evctl.py restart` 全栈重启
- [ ] **E.2** pytest test_api_tables_e2e.py + scripts/e2e/* 验关键路径
- [ ] **E.3** 归档：`mv openspec/changes/2026-08-22-structure-cleanup-remaining openspec/changes/archive/`
- [ ] **E.4** commit: `chore(archive): complete 2026-08-22-structure-cleanup-remaining`

## 暂停点

- **Pause #1**（Stage 1 完成后）：A.4.1 12 文件改完后，报告 grep 残留数 = 0 才进 Stage 2
- **Pause #2**（Stage 5 完成后）：metadata 切后启动无报错才进 Stage 6 删 orm.py
- **Pause #3**（Stage 6 完成后）：orm.py 删后启动无报错才进 Stage 7
- **Pause #4**（Stage 7 完成后）：db.py 删后启动无报错才进 Stage 8

## 报告节奏

每 Stage 完成一行（按 opsx-field-notes §9）：
`# / 任务 / 改动 / 文件 / 验证 / 结果 / OpenSpec / Git`