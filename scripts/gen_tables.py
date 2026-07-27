#!/usr/bin/env python3
"""
scripts/gen_tables.py — tables-codegen 代码生成器

读 MySQL INFORMATION_SCHEMA, 为每张表生成 server/tables/<表名>.py
每个文件包含:
  - 一个类 (PascalCase 表名) 继承 TableBase
  - __tablename__, __pk_fields__, __fields__, __field_types__, __auto_increment_pk__
  - 全部字段作为类属性 type hint (供 IDE 智能提示)
  - 统一使用 upsert_one 作为写入入口，不单独宣传 add_one/update_one

用法:
  python scripts/gen_tables.py             # 生成所有表
  python scripts/gen_tables.py --table orders  # 只生成单张表
  python scripts/gen_tables.py --dry-run    # 只打印, 不写文件

新表 / 字段改动后:
  重新跑此脚本即可, 已存在的文件会被覆盖.
"""
import argparse
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import pymysql

# ────────────────────────── MySQL → Python type 映射 ──────────────────────────
# 简化版: 仅用于生成 type hint (不强制运行时校验, TableBase 是动态 SQL)
TYPE_MAP = {
    "tinyint": "int",
    "smallint": "int",
    "mediumint": "int",
    "int": "int",
    "bigint": "int",
    "float": "float",
    "double": "float",
    "decimal": "float",       # 简化: 所有数值 → float
    "varchar": "str",
    "char": "str",
    "text": "str",
    "mediumtext": "str",
    "longtext": "str",
    "datetime": "datetime",   # from datetime import datetime
    "timestamp": "datetime",
    "date": "date",           # from datetime import date
    "time": "time",           # from datetime import time
    "json": "Any",            # from typing import Any
    "blob": "bytes",
    "tinyint(1)": "bool",     # MySQL boolean 习惯
}


def mysql_to_python(mysql_type: str) -> str:
    """MySQL 类型 → Python type hint 字符串"""
    t = mysql_type.lower().split("(")[0]
    # 处理 tinyint(1) (boolean 习惯)
    if re.match(r"tinyint\(1\)", mysql_type.lower()):
        return "bool"
    return TYPE_MAP.get(t, "Any")


def python_to_import(t: str) -> List[str]:
    """Python type hint 需要 import 的模块"""
    if t == "datetime":
        return ["from datetime import datetime"]
    if t == "date":
        return ["from datetime import date"]
    if t == "time":
        return ["from datetime import time"]
    if t == "Any":
        return ["from typing import Any"]
    return []


# ────────────────────────── 表名 → 类名 ──────────────────────────
def table_to_classname(table_name: str) -> str:
    """snake_case → PascalCase
    orders → Orders
    order_no_seq → OrderNoSeq
    t0_tasks → T0Tasks
    """
    # 数字开头: t0_tasks → T0Tasks
    parts = re.split(r"[_]", table_name)
    return "".join(p[:1].upper() + p[1:] for p in parts)


def field_to_safename(field: str) -> str:
    """字段名 → 安全的 Python 属性名 (一般不需要, 但兜底)"""
    return re.sub(r"[^a-zA-Z0-9_]", "_", field)


# ────────────────────────── 读 MySQL schema ──────────────────────────
def fetch_schema(host: str, port: int, user: str, password: str, db: str) -> List[Dict]:
    """读所有表的 schema, 返回 [{name, comment, columns: [...], pk: [...]}, ...]"""
    conn = pymysql.connect(host=host, port=port, user=user, password=password, database=db)
    cur = conn.cursor()

    # 1. 所有表
    cur.execute("""
        SELECT TABLE_NAME, TABLE_COMMENT
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA=%s
        ORDER BY TABLE_NAME
    """, (db,))
    table_rows = cur.fetchall()

    schemas = []
    for table_name, table_comment in table_rows:
        # 2. 字段
        cur.execute("""
            SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_KEY,
                   COLUMN_DEFAULT, EXTRA, COLUMN_COMMENT
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s
            ORDER BY ORDINAL_POSITION
        """, (db, table_name))
        cols = []
        for cname, ctype, nullable, key, default, extra, comment in cur.fetchall():
            cols.append({
                "name": cname,
                "mysql_type": ctype,
                "python_type": mysql_to_python(ctype),
                "nullable": nullable == "YES",
                "is_pk": key == "PRI",
                "default": default,
                "extra": extra,
                "comment": comment or "",
            })
        pk_cols = [c["name"] for c in cols if c["is_pk"]]
        auto_inc = next((c["name"] for c in cols if "auto_increment" in (c["extra"] or "")), None)
        schemas.append({
            "table": table_name,
            "comment": table_comment or "",
            "columns": cols,
            "pk": pk_cols,
            "auto_inc": auto_inc,
        })

    conn.close()
    return schemas


# ────────────────────────── 渲染单表文件 ──────────────────────────
def render_table_file(schema: Dict) -> str:
    """生成单表 Python 代码"""
    cls = table_to_classname(schema["table"])
    table = schema["table"]
    pk_fields = schema["pk"]
    auto_inc = schema["auto_inc"]
    columns = schema["columns"]

    # 收集所有需要的 imports
    imports = set()
    imports.add("from typing import Any, ClassVar, Tuple")
    for col in columns:
        imports.update(python_to_import(col["python_type"]))
    imports.add("from server.tables.base import TableBase, Row")

    # 字段 type hint 字典 (用于 __annotations__)
    field_annotations = []
    for col in columns:
        t = col["python_type"]
        field_annotations.append(f"    {col['name']}: {t}")
    annotations_str = "\n".join(field_annotations) if field_annotations else "    pass"

    # 字段注释字典 (写到 Row.comments 用)
    fields_dict_lines = []
    for col in columns:
        # Python 字符串字面量: 单引号转义
        c = col["comment"].replace("\\", "\\\\").replace("'", "\\'")
        fields_dict_lines.append(f"        '{col['name']}': '{c}'")
    fields_dict_str = ",\n".join(fields_dict_lines)

    # 字段类型字典
    field_types_lines = []
    for col in columns:
        t = col["mysql_type"].replace("\\", "\\\\").replace("'", "\\'")
        field_types_lines.append(f"        '{col['name']}': '{t}'")
    field_types_str = ",\n".join(field_types_lines)

    # pk_fields tuple — 注意单字段也要写成 ('id',) 而不是 ('id')
    if len(pk_fields) == 1:
        pk_tuple = f"('{pk_fields[0]}',)"
    else:
        pk_tuple = "(" + ", ".join(f"'{p}'" for p in pk_fields) + ")"

    # auto_increment
    auto_inc_str = f"'{auto_inc}'" if auto_inc else "None"

    # 表注释作为类 docstring 第一行
    table_doc = schema["comment"].strip() or f"MySQL table `{table}`"

    code = f'''"""
server/tables/{table}.py — 自动生成 (tables-codegen skill)

表: `{table}`  ({len(columns)} 字段, 主键: {pk_fields})
描述: {table_doc}

⚠️ 不要手动修改本文件 — 任何字段/主键变更请重新跑 tables-codegen
"""
{chr(10).join(sorted(imports))}


class {cls}(TableBase):
    """{table_doc}

    自动生成，继承 TableBase 获得标准方法:
      - query_one(**pk)              按主键查单行 → Row | None
      - upsert_one(data, **pk)       INSERT OR UPDATE（统一写入入口）
      - delete_one(**pk)             按主键 DELETE → bool
      - query_all(order)             全表查询 → List[Row]
      - query_by(field, value)       单字段过滤
      - query_by_fields(filters)     多字段 AND 过滤

    主键: {pk_fields}
    """

    __tablename__: ClassVar[str] = '{table}'
    __pk_fields__: ClassVar[Tuple[str, ...]] = {pk_tuple}
    __auto_increment_pk__: ClassVar[str | None] = {auto_inc_str}

    __fields__: ClassVar[dict] = {{
{fields_dict_str}
    }}

    __field_types__: ClassVar[dict] = {{
{field_types_str}
    }}

    # 字段 type hints (IDE 智能提示用, 运行时不影响行为)
{annotations_str}
'''
    return code


# ────────────────────────── 生成 __init__.py ──────────────────────────
def render_init(schemas: List[Dict]) -> str:
    """生成 server/tables/__init__.py 导出所有表类"""
    lines = [
        '"""',
        'server/tables/__init__.py — 统一导出所有表类 (v80.2 自动生成)',
        '',
        '⚠️ 不要手动修改本文件 — 重新跑 scripts/gen_tables.py 自动更新',
        '"""',
        '',
        'from server.tables.base import TableBase, Row, get_conn  # noqa: F401',
        '',
    ]
    for s in schemas:
        cls = table_to_classname(s["table"])
        lines.append(f"from server.tables.{s['table']} import {cls}  # noqa: F401")
    return "\n".join(lines) + "\n"


# ────────────────────────── main ──────────────────────────
def main():
    ap = argparse.ArgumentParser(description="v80.2 tables code generator")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=33066)
    ap.add_argument("--user", default="EvTrade")
    ap.add_argument("--password", default="p@ssw0rd")
    ap.add_argument("--db", default="evtrade")
    ap.add_argument("--out", default="server/tables")
    ap.add_argument("--table", help="只生成指定表 (默认全部)")
    ap.add_argument("--dry-run", action="store_true", help="只打印不写文件")
    args = ap.parse_args()

    schemas = fetch_schema(args.host, args.port, args.user, args.password, args.db)
    if args.table:
        schemas = [s for s in schemas if s["table"] == args.table]
        if not schemas:
            print(f"❌ 表 {args.table!r} 不存在", file=sys.stderr)
            return 1

    print(f"📋 读 MySQL {args.host}:{args.port}/{args.db} → {len(schemas)} 张表")

    out_dir = Path(args.out)
    if not args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)

    for s in schemas:
        code = render_table_file(s)
        out_file = out_dir / f"{s['table']}.py"
        if args.dry_run:
            print(f"  [dry-run] {out_file} ({len(code)} bytes)")
        else:
            out_file.write_text(code, encoding="utf-8")
            print(f"  ✅ {out_file} ({len(code)} bytes)")

    # 生成 __init__.py
    init_code = render_init(schemas)
    init_file = out_dir / "__init__.py"
    if args.dry_run:
        print(f"  [dry-run] {init_file} ({len(init_code)} bytes)")
    else:
        init_file.write_text(init_code, encoding="utf-8")
        print(f"  ✅ {init_file} ({len(init_code)} bytes)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
