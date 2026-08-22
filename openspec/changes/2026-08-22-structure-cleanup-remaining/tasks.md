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

- [ ] **A.3.1** 改 `server/infra/db.py` L182 `from server.models import user, orm` → `import server.tables`
- [ ] **A.3.2** 改 `server/alembic/env.py` L46 同上
- [ ] **A.3.3** 验 `python -c "from server.infra.db import Base; print(len(Base.metadata.tables))"` > 0
- [ ] **A.3.4** commit: `refactor(db): metadata registration source from orm.py to tables/`

## Stage 6 — A.7 删除 ORM 文件

- [ ] **A.7.1** `grep -rn "from server.models.orm\|from server.models import.*orm" server/ --include="*.py"` 必须 = 0
- [ ] **A.7.2** `git rm server/models/orm.py`
- [ ] **A.7.3** 验 `python -c "import server.main"` 启动无报错
- [ ] **A.7.4** commit: `refactor(models): delete orm.py (data access layer rewrite complete)`

## Stage 7 — B 删除 db.py 兼容垫片

- [ ] **B.1** 列出 28 个 `from server.db import` 引用方
- [ ] **B.2** 批量改 `from server.db import X` → `from server.infra.db import X`
- [ ] **B.3** `grep -rn "from server.db" server/ --include="*.py"` 必须 = 0
- [ ] **B.4** `git rm server/db.py`
- [ ] **B.5** 验 `python -c "import server.main"` 启动无报错
- [ ] **B.6** commit: `refactor(db): delete server/db.py compatibility shim`

## Stage 8 — D 拆分 client/src/api/index.js

- [ ] **D.1** grep `import.*http.*from.*api` client/src/ 找引用方
- [ ] **D.2** 新建 `client/src/api/http.js`（剪切 index.js L1-111 内容）
- [ ] **D.3** `api/index.js` 顶部改 `import { http, tokenStorage } from './http'`，删除 L1-111
- [ ] **D.4** 同步改 per-feature API 文件（admin.js / ai_analysis.js 等）的 `import { http } from './index'` → `from './http'`
- [ ] **D.5** `cd client && npx vite build` 构建无报错
- [ ] **D.6** commit: `refactor(client): split api/index.js into http.js + index.js`

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