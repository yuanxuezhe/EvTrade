# 数据库迁移与Schema

## 对应代码路径

- `scripts/sync_schema.py`（schema.yml ↔ DB 统一管理器：export / diff / apply）
- `scripts/gen_tables.py`（tables 代码生成器：INFORMATION_SCHEMA → `server/tables/*.py`）
- `scripts/run_all_migrations.py`（按序运行 `server/migrations/` 全部迁移）
- `scripts/migrate_db.py`（evtrade → evtrade_dev 数据拷贝）
- `scripts/regenerate_tables_from_orm.py`、`scripts/sync_schema_to_target.py`（辅助变体）
- `server/schema.yml`（schema 单一真相源）
- `server/migrations/`（一次性迁移脚本目录）、`server/alembic/`（Alembic 骨架）
- `openspec/specs/data-model/spec.md` §Schema Governance（治理规则权威源）

## 功能概述

EvTrade 的数据库表结构以 `server/schema.yml` 为单一真相源。`sync_schema.py` 负责 yml 与 MySQL 双向同步，`gen_tables.py` 从 INFORMATION_SCHEMA 生成 `server/tables/` 动态 ORM 类，`server/migrations/` 承载一次性数据/结构迁移。四者构成"改表"的完整工具链。

## 文件清单

| 代码文件 | 作用 |
|----------|------|
| `scripts/sync_schema.py` | export（DB→yml）/ diff（预览）/ apply（yml→DB+重生 tables） |
| `scripts/gen_tables.py` | 读 INFORMATION_SCHEMA 生成 `server/tables/<表名>.py` + `__init__.py` |
| `scripts/run_all_migrations.py` | 检查表状态 → 按时间序运行 `server/migrations/2026-*.py` |
| `scripts/migrate_db.py` | pymysql 全表复制 evtrade → evtrade_dev（TRUNCATE+INSERT，quote_snapshots 走 upsert） |
| `server/migrations/2026-*.py` | 一次性迁移脚本，约定含 `migrate(engine)` 或 `main()` |
| `server/alembic/` | Alembic 目录（仅 1 个 baseline 快照版本，实际未作为主流程） |

## 核心实现

### schema.yml 语法（YAML 子集，自带 mini parser 无外部依赖）

```yaml
tables:
  <表名>:
    pk: ['列1', '列2']        # 主键列（users 表为空数组 = 无主键声明）
    comment: '表注释'          # 可选，生成类 docstring
    columns:
      <列名>:
        type: String(64)      # SQLAlchemy 风格名：String/Integer/BIGINT/Float/TinyInt/
                              # Boolean/Text/LargeText/JSON/DateTime/SmallInteger
        nullable: false
        default: 0            # Python 侧默认（export 时兜底）
        server_default: ''0'' # MySQL DDL DEFAULT（CURRENT_TIMESTAMP 等）
        autoincrement: true   # AUTO_INCREMENT
    indexes:                  # 可选，普通索引（非唯一）
      ix_<名>: ['列1', '列2']
```

- 类型 → MySQL DDL 映射见 `yaml_to_mysql_ddl`（sync_schema.py:249），大小写/空格不敏感；**未知类型 fallback VARCHAR(255) 有截断风险**，长 JSON 列务必写 `LargeText`
- `yaml_to_mysql_base`（sync_schema.py:225）用于 diff 的归一化类型比较

### sync_schema.py 三个子命令

```bash
uv run python scripts/sync_schema.py export                # 活 DB → schema.yml（初始化/同步用）
uv run python scripts/sync_schema.py export --source-url=$DEV_URL   # 从指定源库导出
uv run python scripts/sync_schema.py diff                  # yml vs DB 预览差异（dry-run）
uv run python scripts/sync_schema.py apply                 # yml → DB（建表/加列/MODIFY/建索引）→ 自动跑 gen_tables
uv run python scripts/sync_schema.py apply --strict        # apply 前先 diff，有 drift 拒绝执行
```

- DB 连接取 `EVTRADE_DB_URL` 环境变量（自动加载 `server/.env.gs` 或 `server/.env`）
- apply 能力范围：CREATE TABLE / ADD COLUMN / MODIFY COLUMN（仅类型变化时）/ CREATE INDEX；**不支持删列删表**（diff 会报 REMOVE 但 apply 不执行）
- `evctl.py start backend` 前置体检只调 `diff`（DIFF-ONLY），不自动 apply

### gen_tables.py（代码生成器）

```bash
uv run python scripts/gen_tables.py                    # 生成所有表
uv run python scripts/gen_tables.py --table orders     # 只生成单表
uv run python scripts/gen_tables.py --dry-run          # 只打印不写
# 默认连接: --host 127.0.0.1 --port 33066 --user EvTrade --password p@ssw0rd --db evtrade
```

每个 `server/tables/<表名>.py` 生成一个继承 `TableBase` 的类（snake_case → PascalCase，如 `t0_tasks → T0Tasks`），包含：

- `__tablename__` / `__pk_fields__` / `__auto_increment_pk__` / `__fields__`（列注释）/ `__field_types__`（MySQL 原始类型）
- 全字段 type hint（MySQL→Python 映射：varchar→str、tinyint(1)→bool、datetime→datetime、json→Any）
- 标准方法：`query_one` / `upsert_one`（统一写入入口）/ `delete_one` / `query_all` / `query_by` / `query_by_fields`

同时重生 `server/tables/__init__.py`，导出全部表类 + base 公共 helper（`get_engine/get_conn/transaction/aggregate/scalar_query/exec_sql`）。生成文件头部标注"不要手动修改"。

### server/migrations/ 一次性迁移

- 命名约定：`YYYY-MM-DD-<动作描述>.py`（如 `2026-08-11-add-strategy-order.py`）
- 每个文件独立可执行，含 `migrate(engine)` 或 `main()`；`run_all_migrations.py` 用 importlib 动态加载按文件名排序执行
- 适用场景：复杂结构变更、数据回填、删列删表（sync_schema apply 做不了的破坏性操作）、种子数据修正

```bash
uv run python scripts/run_all_migrations.py   # 全量跑（先打印各表行数，再逐个跑，最后打印终态）
```

### alembic 的关系

`server/alembic/` 只有 1 个 baseline 快照（`2026_08_06-84ea41eb1f25_baseline_current_schema_snapshot.py`）。项目**实际迁移流程不走 Alembic**，而是 schema.yml + sync_schema + server/migrations 的自研链路；Alembic 目录是历史引入的骨架，`sync_schema.py export` 会排除 `alembic_version` 表。

### 改表标准流程（v130+ Schema Governance）

1. dev 库直接改（或手改 `server/schema.yml`）→ `python scripts/sync_schema.py export` 把变更写回 yml
2. `python scripts/sync_schema.py diff` 确认变更面
3. `git commit` 提交 schema.yml（yml 进版本库是唯一权威）
4. 手动 `python scripts/sync_schema.py apply` 推到目标库（apply 自动重生 tables 代码）
5. 仅 ORM 有改动需要单独重生时：`python scripts/gen_tables.py`
6. 复杂/破坏性变更另写 `server/migrations/YYYY-MM-DD-*.py` 并 `run_all_migrations.py`

### migrate_db.py（环境间数据拷贝）

`evctl.py` 式硬编码连接（192.168.10.2:33066）：源 `evtrade` → 目标 `evtrade_dev`，带 `assert DATABASE() == evtrade_dev` 防误写；普通表 TRUNCATE 后整表 INSERT，`quote_snapshots` 走 `INSERT ... ON DUPLICATE KEY UPDATE`。

## 依赖关系

- 上游：`EVTRADE_DB_URL`（server/.env.gs / .env）；MySQL INFORMATION_SCHEMA 可读权限；`sqlalchemy`、`pymysql`
- 下游：`server/tables/*.py`（backend 全部 DB 访问层）；`evctl.py` 启动体检调 `sync_schema.py diff`；`seed_missing_data.py` 依赖表已建好

## 修改指南

- **加表/加字段**：走上方"改表标准流程"；yml 中长 JSON 文本列写 `LargeText`，勿留大写带空格的旧写法（如 `TEXT ` 会 fallback VARCHAR(255)）
- **删列/删表/改列名**：sync_schema 不支持，写 `server/migrations/` 脚本 + 手动更新 schema.yml
- **迁移脚本**：命名带日期前缀保证执行顺序；写成幂等（重复跑不报错），参考 `test_migration_idempotent.py`
- **gen_tables 生成后 `__pk_fields__` 为空**：检查 INFORMATION_SCHEMA `COLUMN_KEY` 权限（历史上导致 `NotImplementedError: Users.__pk_fields__ not set` → login 500）
- `server/tables/__init__.py` 的 base helper 导出清单须与 `server/tables/base.py` 实际定义对账，缺导出会 ImportError 使 backend 起不来
