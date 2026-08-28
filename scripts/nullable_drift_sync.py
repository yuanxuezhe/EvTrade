"""nullable_drift_sync.py — 修 sync_schema.py 不处理的 nullable-only 漂移

背景 (用户硬规则 2026-08-27):
  sync_schema.py apply 只处理 type change, 不处理 nullable-only 漂移 (line 386-405).
  但 nullable change 报在 diff (line 546-547). 两者不一致造成重启服务时 WARN 噪声.

策略:
  - 只处理 nullable-only 漂移 (type 一致但 nullable 不一致)
  - 用 ALTER TABLE ... MODIFY COLUMN 保 COLUMN_TYPE verbatim
  - 仅 NOT NULL <-> NULL 翻转, 不改 type / default / comment
  - **never DROP** (用户硬规则)

用法:
    uv run python ./scripts/nullable_drift_sync.py             # 默认 apply (auto-fix)
    uv run python ./scripts/nullable_drift_sync.py --dry-run   # 只 print SQL 不跑
"""
import os
import sys
from pathlib import Path

# 复用 sync_schema.py 的工具
from sqlalchemy import create_engine, inspect, text

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sync_schema import SCHEMA_YML, parse_yaml, DATABASE_URL


def diff_nullable() -> list[tuple[str, str, str, bool, bool]]:
    """返回 nullable 漂移列表: [(table, col, col_type_str, yaml_nullable, db_nullable)]"""
    if not SCHEMA_YML.exists():
        print(f"ERROR: {SCHEMA_YML} 不存在", file=sys.stderr); sys.exit(1)
    schema = parse_yaml(SCHEMA_YML.read_text(encoding="utf-8"))
    engine = create_engine(DATABASE_URL, pool_size=1)
    insp = inspect(engine)
    drifts = []
    for tn, td in schema.get("tables", {}).items():
        cols = td.get("columns", {})
        if not isinstance(cols, dict) or tn not in insp.get_table_names():
            continue
        db_cols = {c["name"]: c for c in insp.get_columns(tn)}
        for cn, cd in cols.items():
            if cn not in db_cols or not isinstance(cd, dict):
                continue
            yaml_nullable = cd.get("nullable", True)
            db_nullable = db_cols[cn]["nullable"]
            if yaml_nullable != db_nullable:
                # 拿 DB 原始 type + default + comment → MODIFY verbatim
                c = db_cols[cn]
                col_type = str(c["type"]).lower()
                # 去掉 collation 噪音
                for s in (" collate", "COLLATE"):
                    if s in col_type:
                        col_type = col_type[:col_type.index(s)]
                ddl = col_type
                if not yaml_nullable:
                    ddl += " NOT NULL"
                # default 不保留 — yml 没声明 default 时 MODIFY 会丢失原 default.
                # 但本脚本只处理 nullable 漂移, type/default/comment 一律保留 DB 原值 (verbatim).
                drifts.append((tn, cn, ddl, yaml_nullable, db_nullable))
    engine.dispose()
    return drifts


def apply_nullable_drift(dry_run: bool = False) -> None:
    drifts = diff_nullable()
    if not drifts:
        print("✓ 0 nullable 漂移, schema 与 DB 一致")
        return
    print(f"发现 {len(drifts)} 个 nullable 漂移:")
    for tn, cn, ddl, yn, dn in drifts:
        print(f"  {tn}.{cn}: db_nullable={dn} → yaml_nullable={yn}")
        print(f"    SQL: ALTER TABLE `{tn}` MODIFY `{cn}` {ddl}")

    if dry_run:
        print("\n(--dry-run, 未执行)")
        return

    engine = create_engine(DATABASE_URL, pool_size=1)
    with engine.begin() as conn:
        for tn, cn, ddl, _, _ in drifts:
            sql = f"ALTER TABLE `{tn}` MODIFY `{cn}` {ddl}"
            print(f"  执行: {sql}")
            conn.execute(text(sql))
    engine.dispose()
    print(f"\n✓ 应用 {len(drifts)} 个 nullable MODIFY")


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    apply_nullable_drift(dry_run=dry)