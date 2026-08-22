# ORM与迁移

## 对应代码路径

- `server/models/orm.py`（旧 SQLAlchemy ORM 模型）、`server/models/user.py`
- `server/infra/db.py`（Base / engine / init_db）
- `server/migrations/`（34 个独立幂等迁移脚本 + sqlite-to-mysql-migrate.py 工具脚本）
- `server/alembic/`（Alembic 环境：env.py + versions/）
- `scripts/sync_schema.py`（schema.yml ↔ ORM ↔ DB ↔ tables 统一管理器）
- `server/schema.yml`（schema 单一事实来源）
- `server/lifecycle/seed.py`（启动时自动跑 pending migrations）

## 功能概述

EvTrade 存在三套并存的 schema/迁移机制：① 旧 ORM（models/orm.py，遗留 schema 文档与建表来源，业务读写已迁 tables/）；② 手写独立迁移（server/migrations/，按日期命名，启动时自动执行并用 _applied_migrations 表跟踪）；③ Alembic（由 sync_schema.py apply 自动生成 migration）。统一入口是 `scripts/sync_schema.py`：以 schema.yml 为单一事实来源串起 ORM → Alembic → DB → tables 代码生成。

## 文件清单
| 代码文件 | 作用 |
|----------|------|
| server/models/orm.py | 旧 ORM：orders/trades/positions/assets/sys_config/sys_status/reconcile_report/quote_snapshots/order_no_seq 等表定义（头部注明 spec 同步要求） |
| server/models/user.py | User ORM（仍在使用：鉴权登录、WS sync_update 校验、seed 默认账号） |
| server/infra/db.py | MySQL-only engine、Base=declarative_base()、init_db()（create_all + 幂等列/索引补丁） |
| server/migrations/*.py | 独立迁移脚本（幂等，INFORMATION_SCHEMA 探测后 ALTER），如 add-strategy-visibility、order-no-seq-multi-generator、sqlite-to-mysql-migrate |
| server/alembic/env.py | Alembic 入口：读 EVTRADE_DB_URL，导入 models 注册 metadata |
| server/alembic/versions/ | 目前仅 2026_08_06 baseline_current_schema_snapshot（全量基线） |
| scripts/sync_schema.py | export / diff / apply 三命令的 schema 管理器（自带迷你 YAML parser） |
| server/schema.yml | 全部表 pk/columns/indexes/comment 声明 |

## 核心实现

### models/orm.py（旧 ORM，仅遗留）
- 定义与 schema 一致的 declarative 模型；文件头声明"single source of truth 在 openspec/specs/data-model/spec.md"，改前先改 spec。
- 业务代码禁止 `db.query(Order)` 等直接 ORM 读写；orm.py 存在意义：① init_db create_all 建表元数据；② Alembic autogenerate 对比基准；③ 字段注释历史（各版本 schema 改动记录在类 docstring）。
- models/user.py 的 User 是例外仍活跃（登录 bcrypt 校验、to_dict 序列化）。

### init_db（infra/db.py）
- 用 `EVTRADE_DB_ADMIN_URL`（缺省降级 EVTRADE_DB_URL）create_all 建表（幂等）；
- 内嵌幂等补丁：stocks 加 stktype/scale 列、orders.user_def 索引、sys_config seed cantrdstktypes；
- 生产建议：跑一次后移除 admin URL 防误用。

### migrations/（自动执行）
- 命名 `YYYY-MM-DD-<change-slug>.py`；脚本自含 sys.path/env 加载，直连 EVTRADE_DB_URL；
- 幂等模式：`_column_exists(conn, table, column)`（INFORMATION_SCHEMA 探测）→ 缺失才 ALTER/CREATE；
- `lifecycle/seed.py` 启动时 `_run_pending_migrations()`：扫描目录，未记录在 `_applied_migrations` 表的逐个执行并登记（表不存在则建）。

### alembic/
- env.py：`sys.path` 注入 server/ → load .env → 读 EVTRADE_DB_URL → import models 注册 `target_metadata = Base.metadata`。
- versions 目前只有 baseline 快照，日常增量主要走 migrations/ 手写脚本；sync_schema apply 时也会生成 Alembic migration。
- 手动流程：改 ORM → `alembic revision --autogenerate -m "..."` → 审查 → `alembic upgrade head` → `python scripts/gen_tables.py` 更新 tables。

### scripts/sync_schema.py 联动机制
```
python scripts/sync_schema.py export  # DB → schema.yml（bootstrap 反向导出）
python scripts/sync_schema.py diff    # schema.yml vs DB（dry-run 预览）
python scripts/sync_schema.py apply   # schema.yml → ORM 生成 → Alembic migration → 执行 DB → 重生成 tables 代码
```
- 自带零依赖迷你 YAML parser/emitter；路径定位 `server/schema.yml`，环境加载顺序 server/.env → 根 .env。
- schema.yml 每表结构：`pk: [...]`、`columns: {name: {type/nullable/default/server_default/autoincrement}}`、`indexes: {name: [cols]}`、`comment:`。

### 三套机制关系（推荐改表路径）
1. 改 `server/schema.yml`（唯一事实来源）；
2. `sync_schema.py diff` 确认 → `apply`（生成/更新 ORM + Alembic + DB DDL + server/tables/ 代码）；
3. 重启服务（或手动跑 migrations 脚本）保证存量环境升级；
4. 新字段业务侧只改 tables 调用，不碰 ORM 查询。

## 依赖关系
- 上游：lifecycle/seed（init_db + pending migrations）、sync_schema.py、alembic CLI
- 下游：MySQL（DDL 需 admin 权限账号）、tables/codegen 生成器

## 修改指南
- 禁止手改 `server/tables/` 与 `__init__.py` 生成文件；禁止直接改 DB 不更新 schema.yml（下次 apply 会 diff 出漂移）。
- 新增独立迁移脚本：放 server/migrations/，命名日期前缀，必须幂等（INFORMATION_SCHEMA 探测），启动会自动跑。
- orm.py 改动前先改 openspec data-model spec（文件头约定），并同步 schema.yml。
- SQLite 永久禁用：EVTRADE_DB_URL 非 mysql 前缀直接 RuntimeError。
