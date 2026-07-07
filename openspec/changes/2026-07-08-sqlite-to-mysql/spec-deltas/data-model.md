## ADDED Requirements

### REQ-DATA-MYSQL-001: 字符集与排序规则

- 全库字符集：`utf8mb4`（支持 4 字节 emoji + 中文）
- 默认排序规则：`utf8mb4_unicode_ci`
- 连接 charset：`utf8mb4`

### REQ-DATA-MYSQL-002: 存储引擎与事务

- 存储引擎：`InnoDB`（默认；`MyISAM` 不允许）
- 事务隔离：`READ-COMMITTED`（MySQL 8 默认 `REPEATABLE-READ`，OK 但按业务用 READ-COMMITTED 可减少锁）

### REQ-DATA-MYSQL-003: 索引命名

- 迁移/创建索引名格式：`ix_<table>_<column>...`（与 SQLAlchemy `Index.name` 默认生成一致）
- 现存 SQLite migration 的 `CREATE INDEX IF NOT EXISTS` 保留

### REQ-DATA-MYSQL-004: 一次性数据迁移脚本

- `scripts/migrate_sqlite_to_mysql.py`
- 用 `sqlite3` 读 SQLite，pandas/SQLAlchemy bulk_insert_rows 写 MySQL
- 跳过 schema migration（仅传数据；schema 走 `Base.metadata.create_all`）
- 不可重入：第二次跑前会提示已迁移完成（行数 + checksum 校验）
