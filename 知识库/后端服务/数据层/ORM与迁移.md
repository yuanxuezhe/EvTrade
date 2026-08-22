# ORM与迁移

## 对应代码路径

- `server/tables/`（数据访问唯一入口：TableBase + 每表一个文件）
- `server/tables/metadata.py`（tables/ 表类 → Base.metadata 注册，供 alembic autogenerate）
- `server/infra/db.py`（Base / engine / SessionLocal / init_db）
- `server/migrations/`（34 个独立幂等迁移脚本 + legacy-data-bootstrap.py 历史工具脚本）
- `server/alembic/`（Alembic 环境：env.py + versions/）
- `scripts/sync_schema.py`（schema.yml ↔ DB ↔ tables 统一管理器）
- `server/schema.yml`（schema 单一事实来源）
- `server/lifecycle/seed.py`（启动时自动跑 pending migrations + 默认账号 seed）

## 功能概述

EvTrade 的 schema/迁移机制：`server/schema.yml` 是唯一事实来源；`init_db()` 直接把 schema.yml 渲染成 `text()` DDL 建表（**不依赖** SQLAlchemy metadata）。旧 ORM（`server/models/orm.py`、`server/models/user.py`）已全部删除，业务读写统一走 `server/tables/`。迁移靠两套机制：① 手写独立迁移（server/migrations/，按日期命名，启动时自动执行并用 `_applied_migrations` 表跟踪）；② Alembic（`tables/metadata.py` 把 tables/ 表类注册进 Base.metadata 供 autogenerate 对比，日常增量主要走 migrations/）。

## 文件清单
| 代码文件 | 作用 |
|----------|------|
| server/tables/*.py | 每表一个 TableBase 类（21 张表）；`__init__.py` 统一导出 |
| server/tables/metadata.py | import 时把 tables/ 表类转成 sqlalchemy.Table 注册进 Base.metadata（含 users，幂等） |
| server/infra/db.py | MySQL-only engine、SessionLocal、Base=declarative_base()、init_db()（schema.yml → text() DDL + 幂等列/索引补丁） |
| server/migrations/*.py | 独立迁移脚本（幂等，INFORMATION_SCHEMA 探测后 ALTER），如 add-strategy-visibility、order-no-seq-multi-generator、legacy-data-bootstrap |
| server/alembic/env.py | Alembic 入口：读 EVTRADE_DB_URL，import server.tables.metadata 注册 target_metadata = Base.metadata |
| server/alembic/versions/ | 目前仅 2026_08_06 baseline_current_schema_snapshot（全量基线） |
| scripts/sync_schema.py | export / diff / apply 三命令的 schema 管理器（自带迷你 YAML parser） |
| scripts/gen_tables.py | INFORMATION_SCHEMA → server/tables/*.py 代码生成器 |
| server/schema.yml | 全部表 pk/columns/indexes/comment 声明 |

## 核心实现

### server/tables/（数据层唯一入口）
- 每个 MySQL 表一个 `class Xxx(TableBase)` 文件，暴露字段注释 + `__pk_fields__`/`__field_types__`/`__auto_increment_pk__`；
- 标准方法：`query_one / query_by / query_by_fields / query_by_in / add_one / update_one / update_by_fields / upsert_one / delete_one / query_all`，返回 `Row`（属性+字典双访问，绑定 owner 表类）；
- `Row.update()` 无参自动 PK WHERE + 全字段 SET；`Row.delete()` 自动 PK DELETE；
- 连接复用 `server.infra.db.get_engine()`，不引入新连接池；
- `tables/metadata.py` 在 import 时把全部 21 张表（含 users）注册进 Base.metadata，供 alembic autogenerate 使用。

### init_db（infra/db.py）
- 读 `EVTRADE_DB_ADMIN_URL`（缺省降级 EVTRADE_DB_URL），从 schema.yml 反射缺失表 → `text()` DDL 建表（`CREATE TABLE IF NOT EXISTS`，幂等），**不依赖 Base.metadata**；
- 内嵌幂等补丁：stocks 加 stktype/scale 列、orders.user_def 索引、sys_config seed cantrdstktypes；
- 生产建议：跑一次后移除 admin URL 防误用。

### migrations/（自动执行）
- 命名 `YYYY-MM-DD-<change-slug>.py`；脚本自含 sys.path/env 加载，直连 EVTRADE_DB_URL；
- 幂等模式：`_column_exists(conn, table, column)`（INFORMATION_SCHEMA 探测）→ 缺失才 ALTER/CREATE；
- `lifecycle/seed.py` 启动时 `_run_pending_migrations()`：扫描目录，未记录在 `_applied_migrations` 表的逐个执行并登记（表不存在则建）。

### alembic/
- env.py：`sys.path` 注入 server/ → load .env → 读 EVTRADE_DB_URL → `import server.tables.metadata` 注册 `target_metadata = Base.metadata`（21 张表全注册，declarative ORM 已删除）。
- versions 目前只有 baseline 快照，日常增量主要走 migrations/ 手写脚本；sync_schema apply 时也会生成 Alembic migration。
- 手动流程：改 `server/schema.yml` → `alembic revision --autogenerate -m "..."` → 审查 → `alembic upgrade head` → `python scripts/gen_tables.py` 更新 tables。

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
- MySQL 唯一：`EVTRADE_DB_URL` 必须 `mysql+pymysql://` 前缀。
