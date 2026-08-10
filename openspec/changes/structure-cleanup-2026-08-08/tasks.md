# Tasks — 数据访问层重写 + 结构整理

> A 组按 design.md 的 Phase 0-7 分批，每 phase 独立验证 + commit。
> B/C/D 在 A 完成后做（或并行，但 B 的 db.py 删除依赖 A.3 完成 metadata 切换）。
> 建议每个 phase 一个 commit（见 memory: feedback_commit_granularity）。

## A.0 — 重写 codegen 生成器

> 目标：`scripts/gen_tables.py` 生成 SQLAlchemy Core `Table` 对象而非字符串元数据类。
> 此阶段 tables/ 仍与 orm.py 并存，业务代码未动，可独立验证。

- [x] A.0.1 备份 `scripts/gen_tables.py` 当前实现（git 已有历史，确认能 revert）
- [x] A.0.2 重写 MySQL → SQLAlchemy Column 类型映射（design.md D2）
  - `varchar(n)` → `String(n)` / `char(n)` → `String(n)`
  - `int`/`mediumint`/`bigint` → `Integer`/`BigInteger`
  - `tinyint(1)` → `Boolean`，其他 `tinyint`/`smallint` → `Integer`
  - `float`/`double` → `Float`，`decimal(p,s)` → `Numeric(p, s)`
  - `datetime`/`timestamp` → `DateTime`，`date` → `Date`，`time` → `Time`
  - `text`/`mediumtext`/`longtext` → `Text`，`json` → `JSON`，`blob` → `LargeBinary`
- [x] A.0.3 重写生成模板：每个文件输出 `Table(..., Base.metadata, Column(...))`
- [x] A.0.4 实现 `#codegen:preserve-below` 标记段机制
- [x] A.0.5 实现 PK 检测（`INFORMATION_SCHEMA.COLUMNS.COLUMN_KEY='PRI'`）
- [x] A.0.6 实现默认值读取（`COLUMNS.COLUMN_DEFAULT` → `server_default=text(...)` / `default=...`）
- [x] A.0.7 实现索引生成（`INFORMATION_SCHEMA.STATISTICS` → `Index(...)` 入 `__table_args__`）
- [ ] A.0.8 `python scripts/gen_tables.py --dry-run` 检查生成输出（依赖 MySQL 环境，CI/本机需验证）
- [ ] A.0.9 commit: `refactor(tables): 重写 gen_tables.py 生成 Core Table 对象`

## A.1 — 重写 `server/tables/base.py`

> 目标：`TableBase` 持有 `__table__: Table`，方法改用 Core API。
> `Row` 类不变（轻量字典 + 属性访问）。

- [x] A.1.1 `TableBase` 加 `__table__: Table` 类属性声明
- [x] A.1.2 重写 `query_one`：`cls.__table__.select().where(*(c[pk]==v))` → `result.mappings().first()`
- [x] A.1.3 重写 `add_one`：`cls.__table__.insert().values(data)` → 返回带 PK 的 Row
- [x] A.1.4 重写 `update_one`：`cls.__table__.update().where(...).values(...)` → rowcount
- [x] A.1.5 重写 `delete_one`：`cls.__table__.delete().where(...)` → bool
- [x] A.1.6 重写 `query_all`：`cls.__table__.select().order_by(...)` + 分页
- [x] A.1.7 重写 `upsert_one`：`from sqlalchemy.dialects.mysql import insert` +
  `insert(table).values(data).on_duplicate_key_update(**{k: stmt.inserted[k]})`
- [x] A.1.8 重写 `query_by` / `query_by_fields`：`select().where(...)` 组合
- [x] A.1.9 重写 `Row.update()`（L99-151）：改用 `_owner_class.__table__.update().where(PK).values(...)`，
  去掉字符串拼接
- [x] A.1.10 `aggregate` / `scalar_query` / `exec_sql`：保留 `text()` 入口（复杂聚合兼容），
  内部可选改 `select(func.count())` 但非必须
- [x] A.1.11 `_row_from_mapping`：从 `result.mappings()` 拿 dict 构造 Row（兼容）
- [ ] A.1.12 `python -c "import server.tables.base"` 导入无报错（依赖 MySQL .env）
- [ ] A.1.13 commit: `refactor(tables): 重写 TableBase 使用 Core Table API`

## A.2 — 重新生成 19 个 tables/*.py

> 跑改写后的 codegen 一键重生成。重点检查 `__table_args__` 约束段。

- [x] A.2.1 `python scripts/regenerate_tables_from_orm.py`（从 orm.py 重生成 19 文件，附带 scripts/gen_tables.py codegen 模板已就绪）
- [x] A.2.2 逐文件检查 19 个生成文件，对比 `orm.py` 现有约束：
  - `tables/orders.py`：`orm.py` L86-93 的 6 个 `Index(...)` 已迁移到 `__table_args__`
  - `tables/assets.py`：`orm.py` L195 `CheckConstraint("id = 1")` 已迁移到 `__table_args__`
  - `tables/users.py`：`orm.py` 的 `UniqueConstraint` 已迁移
  - 其他 16 文件同样已通过 `regenerate_tables_from_orm.py` 自动迁移
- [x] A.2.3 补齐缺失约束到手写 `__table_args__` + `#codegen:preserve-below` 段（codegen 模板自动生成该标段）
- [x] A.2.4 `python -c "import server.tables; from server.infra.db import Base; print(sorted(Base.metadata.tables.keys()))"` → 19 张表已全注册
- [ ] A.2.5 `pytest server/tests/ -x --timeout=30` 全量通过（依赖 .env + MySQL 环境，启动后验证）
- [ ] A.2.6 commit: `refactor(tables): 重新生成 19 个表文件用 Core Table`

## A.3 — 切换 metadata 注册源

> 让 alembic + init_db 从 tables/ 而非 orm.py 拿 metadata。
> 用 autogenerate 空 diff 验证等价。

- [x] A.3.1 `server/alembic/env.py` L46：`from server.models import user, orm` →
  `import server.tables  # noqa  # 触发 Core Table 注册到 Base.metadata`
- [x] A.3.2 `server/infra/db.py` L192 `init_db()`：`from server.models import user, orm`
  → `import server.tables`
- [ ] A.3.3 `alembic revision --autogenerate -m "verify-metadata-swap"` 生成**空 diff**
  （证明 orm.py 与 tables/ 的 metadata 等价）；若非空，回 A.2 补约束（依赖 MySQL 环境）
- [ ] A.3.4 `python -c "from server.infra.db import init_db; init_db()"` create_all 成功（依赖 MySQL）
- [ ] A.3.5 `pytest server/tests/ -x` 全量通过（依赖 MySQL）
- [ ] A.3.6 删除 A.3.3 生成的空 diff migration 文件（仅用于验证）
- [ ] A.3.7 commit: `refactor(db): metadata 注册源从 orm.py 切到 tables/`

## A.4.1 — 🟢 低风险业务迁移（SysStatus / QuoteSnapshot）

> `get_active_*` 已内部走 tables，调用方几乎零改动。

- [x] `server/services/guards.py` L19：`from server.models.orm import SysStatus, get_active_trd_date, get_active_sysstatus`
  → `from server.infra.db import get_active_trd_date, get_active_sysstatus`
  （helper 迁到 infra/db.py 或保留在 orm.py 直到 A.7 删除）
- [x] `server/repo/system.py` L14/L34：同上
- [x] `server/services/strategy/quote_consumer.py` L401-405：
  `db.query(QuoteSnapshot).filter(...).order_by(QuoteSnapshot.ts.desc()).first()`
  → `select(__table__).where(...).order_by(...)` (Core API)
- [ ] `pytest server/tests/strategy/` 通过（依赖 MySQL）
- [ ] 手动：503 屏障测试（未做日初 / 非交易时段 / 非 trader）
- [ ] commit: `refactor(services): SysStatus/QuoteSnapshot 引用从 orm 迁到 tables`

## A.4.2 — 🟡 中风险（Order 写路径）

> `Order(...) + db.add()` → `Orders.upsert_one({...})`

- [x] `server/services/strategy/engine.py` L31：`from server.models.orm import Order` →
  `from server.tables import Orders`
- [x] L322-336：`order = Order(...) + db.add(order)` → `Orders.upsert_one({...}, trd_date=..., order_no=...)`
- [x] L360-366：`db.query(Order).filter_by(order_no=x).first()` → `Orders.query_one(order_no=x)` + `o.update()`
- [x] `server/services/strategy/t0/engine.py` L34 + L456 + L495：同上模式
- [x] `server/api/admin/sys_status.py` L34 + L100：`SysStatus` → `SysStatus.query_one(id=1)`
- [ ] `pytest server/tests/strategy/test_engine.py` 通过（依赖 MySQL）
- [ ] `pytest scripts/e2e/test_orders_e2e.py` 通过（依赖 RPC + MySQL）
- [ ] commit: `refactor(strategy): Order 写路径从 ORM 迁到 Tables`

## A.4.3 — 🟠 中高风险（类型签名 + 列表）

> `List[Order]` → `List[Row]`，Row 兼容属性访问。

- [x] `server/services/t0/aggregators.py` L18-L70：`from server.models.orm import Order, Trade`
  → `from server.tables import Orders, Trades + Row`
- [x] `server/services/t0/pnl.py` L15：`Trade` → `Trades + Row`
- [x] `server/services/t0/core.py` L22：`Order` → `Orders + Row`
- [ ] `pytest server/tests/` t0 相关全过（依赖 MySQL）
- [ ] commit: `refactor(t0): aggregators/pnl/core 类型签名从 ORM 迁到 Tables`

## A.4.4 — 🔴 高风险（reconcile Position/Asset 链式）

> `db.add(Position(...)) + db.query(Position).filter().delete()` 链式

- [x] `server/services/reconcile.py` L26-29：删除 `from server.models.orm import Position, Asset`
- [x] grep `Position(` / `Asset(` / `db.query(Position` / `db.query(Asset` 已替换为 Tables API
- [x] `db.add(Position(...))` → `Positions.upsert_one({...}, stock_code=...)`
- [x] `db.query(Position).filter().delete()` → `Positions.delete_one(stock_code=...)` 循环
- [x] `db.query(Asset).first()` / `.delete()` / `db.add(Asset(...))` →
  `Assets.query_one(id=1)` / `Assets.delete_one(id=1)` / `Assets.add_one({...})`
- [ ] `pytest server/tests/` reconcile 相关全过（依赖 MySQL）
- [ ] `pytest scripts/e2e/` 全过（依赖 MySQL + RPC）
- [ ] 手动：日初对账 + admin 调平测试
- [ ] commit: `refactor(reconcile): Position/Asset 链式写从 ORM 迁到 Tables`

## A.5 — 迁出 `services/strategy/models.py` 业务方法

> 6 个 ORM 类方法 + 2 个 JSON helper 迁到 repository 或 service 层。

- [ ] `StrategyRegime.get_required_flags` / `get_exclude_flags` / `set_required_flags` /
  `set_exclude_flags`（L131-141）→ 改为对 `Row` 操作的纯函数，放
  `services/strategy/repository.py` 或新建 `services/strategy/flags.py`
- [ ] `StrategyAudit.get_flags_active` / `set_flags_active` / `get_action_payload` /
  `set_action_payload`（L219-233）→ 同上
- [ ] `_json_dumps` / `_json_loads`（L33-40）→ 若其他文件用，迁到
  `server/utils/json.py` 或 `services/strategy/repository.py`；若只用本文件，删除
- [ ] grep 调用方，更新 import 路径
- [ ] `pytest server/tests/strategy/` 通过
- [ ] commit: `refactor(strategy): ORM 类业务方法迁为 Row 纯函数`

## A.6 — 迁移 `services/strategy/models.py` 7 个 strategy ORM 类引用方

> `Strategy / StrategyRegime / StrategyGrid / StrategyAudit / StrategyScript /
> StrategyTask / StrategyScriptAudit` → tables/ 对应类

- [ ] grep `from server.services.strategy.models import` / `from server.services.strategy import models`
  找所有引用方
- [ ] 逐文件迁移：`Strategy` → `tables.Strategy`，`StrategyRegime` → `tables.StrategyRegime`，...
- [ ] 写路径：`db.add(Strategy(...))` → `Strategies.add_one(Row(...))`
- [ ] 读路径：`db.query(Strategy).filter(...)` → `Strategies.query_by(...)` / `query_one(...)`
- [ ] `pytest server/tests/strategy/` 全过
- [ ] `pytest scripts/e2e/` 全过
- [ ] commit: `refactor(strategy): 7 个 strategy ORM 类引用迁到 Tables`

## A.7 — 删除 ORM 文件

> 前提：A.3-A.6 全完成，grep 确认零残留 import。

- [ ] `grep -rn "from server.models.orm\|from server.models import.*orm\|from server.services.strategy.models\|from server.services.strategy import models" server --include="*.py"` 确认零残留
- [ ] `grep -rn "from server.models.user import" server --include="*.py"` 确认引用方（若 `User` 已用 `tables.Users` 替代则可删 `models/user.py`）
- [ ] 删除 `server/models/orm.py`
- [ ] 删除 `server/services/strategy/models.py`
- [ ] 删除 `server/models/user.py`（若引用方已迁）或保留（若仍有非 ORM 用途）
- [ ] 删除 `server/models/__init__.py`（若目录变空）
- [ ] `python -c "import server.main"` 启动无报错
- [ ] `pytest server/tests/` 全过
- [ ] commit: `refactor(models): 删除 orm.py + strategy/models.py（数据访问层重写完成）`

## B — 删除 `server/db.py` 兼容垫片

> 前提：A.3 已切换 metadata 源（init_db 不再 import server.db）。
> 纯 import 路径替换。

- [ ] B.1 迁移 20 个引用方 `from server.db import X` → `from server.infra.db import X`
  （清单见 design.md，包括 api/admin/*, api/asset, api/holdings, api/positions,
  api/strategy/*, api/t0_*, cache/quote_cache_flusher, crawler/runner, lifecycle/seed,
  models/orm[已删]）
- [ ] B.2 删除 `server/db.py`
- [ ] B.3 `grep -rn "from server.db\|from \.db import" server --include="*.py"` 确认零残留
- [ ] B.4 `python -c "import server.main"` 启动无报错
- [ ] B.5 commit: `refactor(db): 删除 server/db.py 兼容垫片`

## C — 删除 `kb/` 废弃目录

> 零代码引用确认。

- [ ] C.1 对照 `kb/README.md` 迁移映射表，确认所有内容已在 `openspec/specs/`
- [ ] C.2 `git rm -r kb/`
- [ ] C.3 检查根 `README.md` / `.gitignore` 是否有指向 `kb/` 的链接，更新
- [ ] C.4 commit: `chore: 删除废弃 kb/ 知识库目录`

## D — 拆分 `client/src/api/index.js`

> HTTP 基础设施抽到 `api/http.js`，业务 endpoint 留 `api/index.js`。

- [ ] D.1 新建 `client/src/api/http.js`，从 `index.js` 剪切 L1-111：
  - `import axios` / `makeLogger`
  - `API_BASE` / `TOKEN_KEY`
  - `export const http = axios.create({...})`
  - `http.interceptors.request.use(...)`
  - `http.interceptors.response.use(...)`（含 `_isRpcResponse` / `_showRpcError`）
  - `export const setUnauthorizedHandler`
  - `export const tokenStorage`
- [ ] D.2 `api/index.js` 顶部 `import { http, tokenStorage } from './http'`
- [ ] D.3 删除 `index.js` 已剪切的 L1-111
- [ ] D.4 迁移 per-feature API 文件的 `http` 导入：
  - `grep -rn "import.*http.*from.*api" client/src --include="*.js" --include="*.vue"` 找引用方
  - `import { http } from './index'` → `import { http } from './http'`
  - `import { http } from '../api'` → `import { http } from '../api/http'`
  - `import { http } from '../../api'` → `import { http } from '../../api/http'`
- [ ] D.5 `cd client && npm run build` 构建无报错
- [ ] D.6 浏览器手动验证：登录 → 拉持仓/委托 → 下单 → 401 触发登出
- [ ] D.7 `cd client && npm run test`（若有前端单测）
- [ ] D.8 commit: `refactor(client): 拆分 api/index.js 抽出 http.js 基础设施`

## E — 收尾

- [ ] E.1 全量回归：`python scripts/evctl.py restart` + 浏览器冒烟
- [ ] E.2 `pytest server/tests/ && pytest scripts/e2e/` 全过
- [ ] E.3 更新 spec-deltas（若实施中发现 spec 描述需微调）
- [ ] E.4 `openspec validate 2026-08-08-structure-cleanup-no-logic-change`
- [ ] E.5 归档：`mv openspec/changes/2026-08-08-structure-cleanup-no-logic-change openspec/changes/archive/`
