# Proposal — Structure Cleanup Remaining（数据访问层重写续）

## Why

`structure-cleanup-2026-08-08` partial-archive 后，44 个 task 未做（archived at `039ca07`）：
- A.3 metadata 注册源未切（infra/db.py L182 + alembic/env.py L46 仍 `from server.models import orm`）
- A.4.1-A.4.4 12 文件残留 `from server.models.orm` import（guards/repo/system/t0/core/aggregators/pnl/reconcile）
- A.7 `server/models/orm.py` 23745 bytes 仍在
- B `server/db.py` 兼容垫片 28 个引用方未迁
- D `client/src/api/index.js` 332 行未拆
- E 收尾未做

实质推进这些 task 是 EvTrade 数据访问层重写（v81 → v132）的最后阶段：业务代码全用 `tables/` Core API、删 ORM 与兼容垫片、HTTP 基础设施独立。前置任务（A.0-A.2 codegen + base.py + 19 表文件 + C kb/ 删除）已落地。

## What Changes

按依赖顺序 5 个 Stage，每个独立 commit：

| Stage | 改动 | commit |
|---|---|---|
| **A.4.1** | 12 文件迁 `from server.models.orm import X` → `from server.tables import X`（SysStatus/QuoteSnapshot/Order/Position/Asset 等），保留 `get_active_*` helper 在 orm.py 直到 A.7 | `refactor(services): migrate business imports from orm.py to tables/` |
| **A.4.2** | `server/services/strategy/engine.py` `Order(...)`/`db.add(Order)` → `Orders.upsert_one({...})`；确认 `server/services/strategy/t0/engine.py` 同步 | `refactor(strategy): Order write path from ORM to Tables` |
| **A.4.3** | `t0/{core,aggregators,pnl}.py` `List[Order]`/`List[Trade]` → `List[Row]`；Row 属性访问兼容 | `refactor(t0): aggregator/pnl/core type signatures from ORM to Tables` |
| **A.4.4** | `reconcile.py` L220/L236 `db.add(Position(...))`/`db.add(Asset(...))` → `Positions.upsert_one({...})`/`Assets.upsert_one({...})` | `refactor(reconcile): Position/Asset chain write from ORM to Tables` |
| **A.3** | `server/infra/db.py` L182 + `server/alembic/env.py` L46 `from server.models import orm` → `import server.tables` | `refactor(db): metadata registration source from orm.py to tables/` |
| **A.7** | `grep -rn "from server.models.orm\|strategy.models" server --include="*.py"` 确认零残留 → `git rm server/models/orm.py` `server/services/strategy/models.py`（已不存在） | `refactor(models): delete orm.py (data access layer rewrite complete)` |
| **B** | 28 个 `from server.db import X` → `from server.infra.db import X`；`git rm server/db.py` | `refactor(db): delete server/db.py compatibility shim` |
| **D** | `client/src/api/index.js` 332 行拆出 `http.js`（axios instance / interceptors / tokenStorage / setUnauthorizedHandler）；`index.js` 改 `import { http, tokenStorage } from './http'`；更新所有引用方的 import 路径 | `refactor(client): split api/index.js into http.js + index.js` |

## Backward Compatibility

- A.4.x：纯 import 替换 + Table API 改写（行为不变，已有 pytest 覆盖）；新增 `Row` 类型注解
- A.3：metadata 等价（alembic autogenerate 空 diff 验证）；init_db() 行为不变
- A.7：删 orm.py 后任何遗漏的 `from server.models.orm` 会 ImportError——A.4 grep 必须零残留
- B：纯 import 替换；server/db.py 删除后任何遗漏会 ImportError
- D：HTTP 行为不变；只是 import 路径变化

## Risks

- **MySQL 环境不可用**：本机 `EVTRADE_DB_URL` 指向远程 `192.168.10.2:33066`，pytest server/tests/ 需要 MySQL。可用 `python -c "import server.main"` 验启动 + `pytest test_api_tables_e2e.py`（无 MySQL 依赖）验 import。
- **alembic 验证**：A.3 需 `alembic revision --autogenerate` 验证 metadata 等价，需 MySQL。可用 `python -c "from server.infra.db import Base; print(sorted(Base.metadata.tables.keys()))"` 验 metadata 来自 tables/。
- **A.7 grep 残留**：删 orm.py 前必须 `grep -rn "from server.models.orm" server/ --include="*.py"` = 0 matches。若 A.4.x 漏迁，删 orm.py 会导致服务崩溃。
- **D 引用方遗漏**：`client/src/api/index.js` 拆出后任何遗漏 `import { http } from './index'` 会断。前端 Vite 构建会立刻报错（`npm run build`）—— 可用 `cd client && npx vite build` 验。
- **pytest 失败立刻停**：不绕过错误，按 opsx-field-notes §6。

## Decisions

| # | 决策点 | 默认推荐 |
|---|---|---|
| Q1 | A.4.1 helper（get_active_trd_date / get_active_sysstatus）暂留 orm.py vs 迁到 infra/db.py | 暂留 orm.py 直到 A.7 |
| Q2 | A.4.4 reconcile.py L220/L236 链式 delete 用 `delete_one` 循环 vs 批量 `delete().where(...)` | 现有循环模式（A.4.4 tasks.md 描述） |
| Q3 | A.3 init_db() 中 `from server.models import user, orm` → 整体替换为 `import server.tables`（不动 user，user.py 单独处理） | 是 |
| Q4 | B 28 个引用方是否批量 sed 替换 vs 逐文件改 | 批量 sed（单 commit 内一致替换） |
| Q5 | D index.js 拆出 http.js 后，per-feature API 文件（admin.js 等）的 `import { http } from './index'` 路径 | 同步改 `from './http'` |