# Spec Deltas — Server Architecture（数据访问层重写续）

> 追加于：`openspec/specs/server-architecture/spec.md` 末尾
> Change: 2026-08-22-structure-cleanup-remaining

---

### REQ-ARCH-DAL-009: 业务代码统一走 Tables API（2026-08-22）

The system SHALL ensure all business service code accesses the data layer through `server.tables.*` Core API (TableBase + Row), not through SQLAlchemy ORM classes (server.models.orm).

#### Scenario: 业务 import 不引用 orm.py

- **GIVEN** `grep -rn "from server.models.orm" server/ --include="*.py"`
- **WHEN** code 完成 structure-cleanup-remaining 全部 Stage
- **THEN** MUST = 0 matches
- **AND** `git ls-files server/models/orm.py` MUST = empty（已 git rm）

#### Scenario: 数据写入走 Tables API

- **GIVEN** Order/Position/Asset 等表的写路径
- **WHEN** 业务代码插入一行
- **THEN** MUST 用 `TableName.upsert_one({...}, pk_kwargs...)` 或 `TableName.add_one({...})`
- **AND** MUST NOT 直接用 `db.add(ORMClass(...))` 或 `db.session.add(ORMClass(...))`

#### Scenario: 数据读取走 Tables API

- **GIVEN** Order/Position/Asset 等表的读路径
- **WHEN** 业务代码查询一行
- **THEN** MUST 用 `TableName.query_one(pk_kwargs)` 或 `TableName.query_by(**filters)`
- **AND** MUST NOT 直接用 `db.query(ORMClass).filter(...)`

### REQ-ARCH-DAL-010: db.py 兼容垫片移除（2026-08-22）

The system SHALL remove `server/db.py` (legacy `SessionLocal` / `init_db` re-export) after all callers migrate to `server.infra.db`.

#### Scenario: 无 db.py 残留

- **GIVEN** `grep -rn "from server.db" server/ --include="*.py"`
- **WHEN** Stage 7 完成
- **THEN** MUST = 0 matches
- **AND** `git ls-files server/db.py` MUST = empty

### REQ-ARCH-DAL-011: HTTP 基础设施独立模块（2026-08-22）

The system SHALL separate HTTP infrastructure (axios instance + interceptors + token storage) from business endpoints.

#### Scenario: api/http.js 独立

- **GIVEN** `client/src/api/`
- **WHEN** Stage 8 完成
- **THEN** `client/src/api/http.js` MUST 存在且 export `http` / `tokenStorage` / `setUnauthorizedHandler`
- **AND** `client/src/api/index.js` MUST import from `./http` 而非 self-define
- **AND** `cd client && npx vite build` MUST succeed