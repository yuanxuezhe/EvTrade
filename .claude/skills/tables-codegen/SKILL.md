---
name: tables-codegen
description: 根据 MySQL 数据库表结构，自动生成/优化 server/tables/ 下的表类代码。当需要新增表、字段变更、或优化现有表代码时使用。统一使用 upsert_one，不再单独暴露 add_one/update_one。
compatibility: Requires Python 3.10+, pymysql, SQLAlchemy 1.4
metadata:
  author: EvTrade
  version: "1.0"
---

# Tables Codegen Skill

根据 MySQL 数据库表结构，自动生成 `server/tables/<表名>.py` 表类代码，并维护 `__init__.py` 统一导出入口。

## 触发条件

- 数据库新增表，需要同步生成表类
- 现有表字段变更（增删改列、主键调整）
- 优化/重构 tables 层代码
- 用户提到 "生成表代码"、"更新表类"、"tables codegen"

## 核心原则

### 1. 统一写入入口：upsert_one

**项目已明确：不需要单独的 insert (add_one) 和 update (update_one) 逻辑，统一使用 `upsert_one`。**

生成器代码注释中不要出现 add_one / update_one 的用法示例，统一用 `upsert_one`。

基类 `TableBase.add_one()` 和 `TableBase.update_one()` 目前仍有外部调用方（如 repo/quote_snapshots.py、repo/stocks.py），**不要删除基类方法**。但在新生成的表文件 docstring 中，只宣传 `upsert_one`。

### 2. 文件一一对应

每个 MySQL 表对应 `server/tables/<表名>.py` 一个文件，文件名 = MySQL TABLE_NAME（snake_case）。

### 3. 类继承 TableBase

每个生成的类继承 `TableBase`，获得：
- `query_one(**pk)` — 按主键查单行 → `Row | None`
- `upsert_one(data, **pk)` — INSERT OR UPDATE（统一写入入口）
- `delete_one(**pk)` — 按主键 DELETE → bool
- `query_all(order)` — 全表查询 → `List[Row]`
- `query_by(field, value)` — 单字段过滤
- `query_by_fields(filters)` — 多字段 AND 过滤

### 4. 自动文件禁止手动修改

生成的文件 header 必须带警告注释，告知不要手动修改，变更需重新跑生成器。

## 生成步骤

### Step 1: 连接 MySQL 读取 INFORMATION_SCHEMA

```python
import pymysql

conn = pymysql.connect(
    host="127.0.0.1", port=33066,
    user="EvTrade", password="p@ssw0rd",
    database="evtrade"
)
cur = conn.cursor()

# 获取指定表（或全量）
cur.execute("""
    SELECT TABLE_NAME, TABLE_COMMENT
    FROM INFORMATION_SCHEMA.TABLES
    WHERE TABLE_SCHEMA = %s
    ORDER BY TABLE_NAME
""", (db,))

# 获取字段详情
cur.execute("""
    SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_KEY,
           COLUMN_DEFAULT, EXTRA, COLUMN_COMMENT
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
    ORDER BY ORDINAL_POSITION
""", (db, table_name))
```

### Step 2: MySQL 类型 → Python type hint 映射

```
tinyint(1)   → bool
tinyint/smallint/mediumint/int/bigint → int
float/double/decimal              → float
varchar/char/text/mediumtext/longtext → str
datetime/timestamp                → datetime  (from datetime import datetime)
date                              → date      (from datetime import date)
time                              → time      (from datetime import time)
json                              → Any       (from typing import Any)
blob                              → bytes
```

### Step 3: 命名转换

- **表名 → 类名**: snake_case → PascalCase（`order_no_seq` → `OrderNoSeq`，`t0_tasks` → `T0Tasks`）
- **文件名**: 直接使用 MySQL 表名（snake_case），如 `quote_snapshots.py`

### Step 4: 渲染文件模板

每个 `<表名>.py` 文件结构：

```python
"""
server/tables/<表名>.py — 自动生成 (tables-codegen skill)

表: `<表名>`  (N 字段, 主键: [pk_fields])
描述: <表注释>

⚠️ 不要手动修改本文件 — 任何字段/主键变更请重新跑 tables-codegen
"""
from typing import Any, ClassVar, Tuple
from server.tables.base import TableBase, Row


class <PascalCase>(TableBase):
    """<表注释>

    自动生成，继承 TableBase 获得标准方法:
      - query_one(**pk)              按主键查单行 → Row | None
      - upsert_one(data, **pk)       INSERT OR UPDATE（统一写入）
      - delete_one(**pk)             按主键 DELETE → bool
      - query_all(order)             全表查询 → List[Row]
      - query_by(field, value)       单字段过滤
      - query_by_fields(filters)     多字段 AND 过滤

    主键: <pk_fields>
    """

    __tablename__: ClassVar[str] = '<表名>'
    __pk_fields__: ClassVar[Tuple[str, ...]] = ('pk_field',)  # 单字段加逗号
    __auto_increment_pk__: ClassVar[str | None] = 'id'  # 或 None

    __fields__: ClassVar[dict] = {
        'field_name': '字段注释',
        # ...
    }

    __field_types__: ClassVar[dict] = {
        'field_name': 'mysql_type',
        # ...
    }

    # 字段 type hints (IDE 智能提示)
    field_name: python_type
    # ...
```

### Step 5: 更新 __init__.py

`server/tables/__init__.py` 必须导出所有表类。新增表后追加导入行：

```python
from server.tables.<表名> import <类名>  # noqa: F401
```

**注意**: `__init__.py` 手改动得较多（如额外从 base 导出 transaction、aggregate），如果已存在且仅少了新表的导入，只追加新表那一行，不要全量覆盖。

## 关键注意事项

1. **复合主键**: `__pk_fields__` 必须写成 tuple，单字段也要 `('id',)` 而非 `('id')`
2. **自增主键**: `__auto_increment_pk__` 仅在字段 EXTRA 含 `auto_increment` 时设置
3. **转义**: 字段注释中的单引号 `'` → `\'`，反斜杠 `\` → `\\`
4. **排序**: imports 按字母序排序；字段按 ORDINAL_POSITION（数据库定义顺序）
5. **不要删除基类方法**: `add_one`/`update_one` 仍有调用方，只在新文件 docstring 中不宣传
6. **不要生成业务逻辑**: 表文件只含元数据 + type hints，业务 CRUD 放 `server/repo/` 层

## 快速命令

```bash
# 生成所有表
python scripts/gen_tables.py

# 只生成单张表
python scripts/gen_tables.py --table <表名>

# 预览不写入
python scripts/gen_tables.py --dry-run
```
