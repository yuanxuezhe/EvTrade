#!/usr/bin/env python3
"""
scripts/sync_schema.py — Unified Schema Manager

Usage:
  python scripts/sync_schema.py export   # DB -> schema.yml (bootstrap)
  python scripts/sync_schema.py diff     # schema.yml vs DB (dry-run)
  python scripts/sync_schema.py apply    # schema.yml -> ORM -> DB -> tables

Workflow:
  1. Run `export` once to generate server/schema.yml from live DB
  2. Edit server/schema.yml to add/modify tables or columns
  3. Run `diff` to preview changes
  4. Run `apply` to execute: generates ORM -> Alembic migration -> DB -> tables code
"""
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.dirname(__file__))

try:
    from dotenv import load_dotenv
    _ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server", ".env")
    if not os.path.exists(_ENV_PATH):
        _ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
    if os.path.exists(_ENV_PATH):
        load_dotenv(_ENV_PATH, override=False)
except ImportError:
    pass

from sqlalchemy import create_engine, inspect, text

DATABASE_URL = os.environ.get("EVTRADE_DB_URL", "")
SCHEMA_YML = Path(__file__).parent.parent / "server" / "schema.yml"


# ── Minimal YAML parser/emitter (no external dependency) ──

def parse_yaml(text):
    lines = text.split('\n')
    return _parse_mapping(lines, 0, 0)[0]

def _indent(line):
    return len(line) - len(line.lstrip())

def _parse_value(val):
    val = val.strip()
    if not val or val in ('~', 'null'):
        return None
    if val in ('true', 'True'):
        return True
    if val in ('false', 'False'):
        return False
    if val.startswith('[') and val.endswith(']'):
        return [_parse_value(x) for x in val[1:-1].split(',') if x.strip()]
    if val.startswith('{') and val.endswith('}'):
        return _parse_flow_dict(val)
    if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
        return val[1:-1]
    try:
        return int(val)
    except ValueError:
        pass
    try:
        return float(val)
    except ValueError:
        pass
    return val

def _parse_flow_dict(s):
    result = {}
    inner = s[1:-1].strip()
    if not inner:
        return result
    for part in _split_flow(inner):
        part = part.strip()
        if ':' in part:
            k, v = part.split(':', 1)
            result[k.strip().strip("'\"")] = _parse_value(v)
    return result

def _split_flow(s):
    parts, depth, current = [], 0, []
    for ch in s:
        if ch in ('{', '['):
            depth += 1; current.append(ch)
        elif ch in ('}', ']'):
            depth -= 1; current.append(ch)
        elif ch == ',' and depth == 0:
            parts.append(''.join(current)); current = []
        else:
            current.append(ch)
    if current:
        parts.append(''.join(current))
    return parts

def _parse_mapping(lines, start, base_indent):
    result = {}
    i = start
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            i += 1; continue
        ind = _indent(line)
        if ind < base_indent:
            break
        if ind > base_indent and i == start:
            break
        if ':' in stripped:
            cp = stripped.index(':')
            key = stripped[:cp].strip()
            vp = stripped[cp+1:].strip()
            if vp:
                result[key] = _parse_value(vp)
                i += 1
            else:
                j = i + 1
                while j < len(lines) and (not lines[j].strip() or lines[j].strip().startswith('#')):
                    j += 1
                if j < len(lines):
                    ni = _indent(lines[j])
                    ns = lines[j].strip()
                    if ni > ind and ns.startswith('- '):
                        lst, i = _parse_list(lines, j, ni)
                        result[key] = lst
                    elif ni > ind:
                        child, i = _parse_mapping(lines, j, ni)
                        result[key] = child
                    else:
                        result[key] = None; i += 1
                else:
                    result[key] = None; i += 1
        else:
            i += 1
    return result, i

def _parse_list(lines, start, base_indent):
    result = []
    i = start
    while i < len(lines):
        s = lines[i].strip()
        if not s or s.startswith('#'):
            i += 1; continue
        if _indent(lines[i]) < base_indent:
            break
        if s.startswith('- '):
            item = s[2:].strip()
            result.append(_parse_value(item))
            i += 1
        else:
            i += 1
    return result, i

def dump_yaml(data):
    lines = []
    _dump_map(data, lines, 0)
    return '\n'.join(lines) + '\n'

def _dump_map(d, lines, ind):
    p = '  ' * ind
    for k, v in d.items():
        if isinstance(v, dict):
            lines.append(f"{p}{k}:")
            _dump_map(v, lines, ind + 1)
        elif isinstance(v, list):
            if len(v) == 0:
                lines.append(f"{p}{k}: []")
            elif all(isinstance(x, str) for x in v):
                lines.append(f"{p}{k}: {v}")
            else:
                lines.append(f"{p}{k}:")
                for item in v:
                    lines.append(f"{p}  - {_fmt(item)}")
        else:
            lines.append(f"{p}{k}: {_fmt(v)}")

def _fmt(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        if any(c in v for c in ':{}[]#*&!|>@"\''):
            return f"'{v}'"
        return v
    return str(v)


# ── Type mappings ──

def mysql_to_yaml(mysql_type):
    t = mysql_type.lower()
    raw = mysql_type
    # Strip COLLATE info
    for sep in (" collate", "COLLATE"):
        if sep in raw:
            raw = raw[:raw.index(sep)]
            t = raw.lower()
    if t.startswith("varchar(") or t.startswith("varchar ("):
        # Extract just the size: VARCHAR(16) → String(16)
        m = re.search(r'varchar\s*\((\d+)\)', raw, re.IGNORECASE)
        return f"String({m.group(1)})" if m else f"String{raw[raw.index('('):]}"
    if t in ("tinyint(1)", "tinyint (1)"):
        return "Boolean"
    if "(" in t:
        base = t[:t.index('(')]
    else:
        base = t
    m = {"int": "Integer", "integer": "Integer", "bigint": "BIGINT",
         "smallint": "SmallInteger", "tinyint": "TinyInt",
         "float": "Float", "double": "Float", "decimal": "Float",
         "text": "Text", "longtext": "LargeText", "mediumtext": "Text",
         "datetime": "DateTime", "timestamp": "DateTime", "json": "JSON",
         "char": "String", "double": "Float"}
    return m.get(base, raw)

def yaml_to_mysql_base(yt):
    b = yt.split("(")[0]
    return {"String": "varchar", "Integer": "integer", "BIGINT": "bigint",
            "SmallInteger": "smallint", "TinyInt": "tinyint", "Float": "float", "Boolean": "tinyint",
            "Text": "text", "LargeText": "longtext", "JSON": "json",
            "DateTime": "datetime"}.get(b, b.lower())

def yaml_to_mysql_ddl(yt):
    """YAML type -> MySQL DDL for ALTER TABLE."""
    m = re.match(r'(\w+)\((\d+)\)', yt)
    if m:
        return f"VARCHAR({m.group(2)})"
    return {"Integer": "INT", "BIGINT": "BIGINT", "SmallInteger": "SMALLINT",
            "TinyInt": "TINYINT", "Float": "FLOAT", "Boolean": "TINYINT(1)",
            "Text": "TEXT", "LargeText": "LONGTEXT", "JSON": "JSON",
            "DateTime": "DATETIME"}.get(yt, "VARCHAR(255)")

def python_default(mysql_type):
    t = mysql_type.lower().split("(")[0]
    if t in ("int", "integer", "bigint", "smallint", "tinyint"):
        return 0
    if t in ("float", "double", "decimal"):
        return 0.0
    return ""

# ── Export: DB -> schema.yml ──

def export_schema():
    if not DATABASE_URL or not DATABASE_URL.startswith("mysql"):
        print("ERROR: EVTRADE_DB_URL not set or not MySQL", file=sys.stderr); sys.exit(1)
    engine = create_engine(DATABASE_URL, pool_size=1, pool_pre_ping=True)
    insp = inspect(engine)
    tables_data = {}
    for tn in sorted(insp.get_table_names()):
        if tn == "alembic_version":
            continue
        columns = {}
        for col in insp.get_columns(tn):
            entry = {"type": mysql_to_yaml(str(col["type"])), "nullable": col["nullable"]}
            if col["default"] is not None:
                entry["server_default"] = col["default"]
            elif not col["nullable"]:
                entry["default"] = python_default(str(col["type"]))
            if col.get("autoincrement") is True:
                entry["autoincrement"] = True
            columns[col["name"]] = entry
        pk = insp.get_pk_constraint(tn).get("constrained_columns", [])
        indexes = {}
        for idx in insp.get_indexes(tn):
            if not idx["unique"] and idx.get("column_names"):
                indexes[idx["name"]] = idx["column_names"]
        info = {"pk": pk, "columns": columns}
        if indexes:
            info["indexes"] = indexes
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT TABLE_COMMENT FROM INFORMATION_SCHEMA.TABLES "
                "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=:t"), {"t": tn}).fetchone()
            if row and row[0]:
                info["comment"] = row[0]
        tables_data[tn] = info
    schema = {"tables": tables_data}
    with open(SCHEMA_YML, "w", encoding="utf-8") as f:
        f.write("# EvTrade database schema\n")
        f.write("# Edit this file, then: python scripts/sync_schema.py apply\n\n")
        f.write(dump_yaml(schema))
    print(f"Exported {len(tables_data)} tables to {SCHEMA_YML}")
    engine.dispose()


# ── Apply: schema.yml -> ORM -> DB -> tables ──

def apply_schema():
    if not SCHEMA_YML.exists():
        print(f"ERROR: {SCHEMA_YML} not found. Run `export` first.", file=sys.stderr); sys.exit(1)
    with open(SCHEMA_YML, "r", encoding="utf-8") as f:
        schema = parse_yaml(f.read())
    if not DATABASE_URL or not DATABASE_URL.startswith("mysql"):
        print("ERROR: EVTRADE_DB_URL not set", file=sys.stderr); sys.exit(1)
    engine = create_engine(DATABASE_URL, pool_size=1, pool_pre_ping=True)
    insp = inspect(engine)
    applied = 0
    tables = schema.get("tables", {})
    db_tables = set(insp.get_table_names())

    for tn, td in tables.items():
        columns = td.get("columns", {})
        indexes = td.get("indexes", {})
        pk = td.get("pk", [])

        # Create table if missing
        if tn not in db_tables:
            sql = _build_create_table(tn, td)
            print(f"Creating table {tn}...")
            with engine.begin() as conn:
                conn.execute(text(sql))
            print(f"  Created {tn}")
            applied += 1
            db_tables.add(tn)
            continue

        # Add/modify columns
        if not isinstance(columns, dict):
            continue
        db_cols = {c["name"]: c for c in insp.get_columns(tn)}
        for cn, cd in columns.items():
            if not isinstance(cd, dict):
                continue
            if cn not in db_cols:
                # Add column
                col_def = _build_column_def(cn, cd)
                sql = f"ALTER TABLE `{tn}` ADD COLUMN {col_def}"
                print(f"Adding column {tn}.{cn}...")
                with engine.begin() as conn:
                    conn.execute(text(sql))
                print(f"  Added {tn}.{cn}")
                applied += 1
            else:
                # Check type change (same normalization logic as diff_schema)
                yb = yaml_to_mysql_base(str(cd.get("type", "")))
                db_t = str(db_cols[cn]["type"]).lower()
                for sep in (" collate", "COLLATE"):
                    if sep in db_t:
                        db_t = db_t[:db_t.index(sep)]
                db_b = db_t[:db_t.index('(')] if '(' in db_t else db_t
                # Normalize DB type to match yaml_to_mysql_base output
                db_norm = {"int": "integer", "tinyint": "tinyint"}.get(db_b, db_b)
                if yb != db_norm:
                    ddl_t = yaml_to_mysql_ddl(str(cd.get("type", "String(255)")))
                    sql = f"ALTER TABLE `{tn}` MODIFY `{cn}` {ddl_t}"
                    if not cd.get("nullable", True):
                        sql += " NOT NULL"
                    print(f"Modifying column type {tn}.{cn}: {db_b} -> {yb}...")
                    with engine.begin() as conn:
                        conn.execute(text(sql))
                    print(f"  Modified {tn}.{cn}")
                    applied += 1

        # Add indexes
        if isinstance(indexes, dict):
            existing_idx = {idx["name"]: idx for idx in insp.get_indexes(tn)}
            for idx_name, idx_cols in indexes.items():
                if idx_name not in existing_idx and isinstance(idx_cols, list):
                    cols_str = ", ".join(f"`{c}`" for c in idx_cols)
                    sql = f"CREATE INDEX `{idx_name}` ON `{tn}` ({cols_str})"
                    print(f"Creating index {idx_name} on {tn}...")
                    with engine.begin() as conn:
                        try:
                            conn.execute(text(sql))
                            print(f"  Created index {idx_name}")
                            applied += 1
                        except Exception as e:
                            if "Duplicate" in str(e):
                                print(f"  Index {idx_name} already exists, skipped")
                            else:
                                raise

    if applied == 0:
        print("No changes to apply — schema.yml matches live DB.")
    else:
        print(f"\nApplied {applied} change(s)")
        # Regenerate table code
        run_gen_tables()
    engine.dispose()


def _build_create_table(tn, td):
    """Build CREATE TABLE SQL from schema definition."""
    columns = td.get("columns", {})
    pk = td.get("pk", [])
    lines = [f"CREATE TABLE `{tn}` ("]
    parts = []
    if not isinstance(columns, dict):
        columns = {}
    for cn, cd in columns.items():
        if not isinstance(cd, dict):
            continue
        col_def = _build_column_def(cn, cd)
        if cn in pk:
            col_def += " PRIMARY KEY"
        parts.append(f"    {col_def}")
    if len(pk) > 1:
        pk_str = ", ".join(f"`{c}`" for c in pk)
        parts.append(f"    PRIMARY KEY ({pk_str})")
    for iname, icols in td.get("indexes", {}).items():
        if isinstance(icols, list):
            parts.append(f"    INDEX `{iname}` ({', '.join(f'`{c}`' for c in icols)})")
    lines.append(",\n".join(parts))
    lines.append(") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4")
    return "\n".join(lines)


def _build_column_def(cn, cd):
    """Build column definition SQL."""
    sa = yaml_to_mysql_ddl(str(cd.get("type", "String(255)")))
    result = f"`{cn}` {sa}"
    if not cd.get("nullable", True):
        result += " NOT NULL"
    sd = cd.get("server_default")
    if sd is not None:
        fsd = _fmt_sd(sd)
        if fsd:
            result += f" DEFAULT {fsd}"
    if cd.get("autoincrement"):
        result += " AUTO_INCREMENT"
    return result

def _fmt_sd(sd):
    if isinstance(sd, str):
        s = sd.strip()
        if s.lower().startswith("current_timestamp"):
            return repr(s)
        if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
            return repr(s)
        try:
            float(s); return repr(s)
        except ValueError:
            pass
    return None


# ── Subprocess helpers ──

def run_gen_tables():
    gs = Path(__file__).parent / "gen_tables.py"
    if not gs.exists():
        print("WARNING: gen_tables.py not found", file=sys.stderr); return
    env = os.environ.copy(); env["PYTHONIOENCODING"] = "utf-8"
    print("\n--- Generate tables ---")
    r = subprocess.run([sys.executable or "python", str(gs)],
                       env=env, capture_output=True, text=True)
    print(r.stdout); print(r.stderr, file=sys.stderr)


# ── Diff ──

def diff_schema():
    if not SCHEMA_YML.exists():
        print(f"ERROR: {SCHEMA_YML} not found", file=sys.stderr); sys.exit(1)
    if not DATABASE_URL or not DATABASE_URL.startswith("mysql"):
        print("ERROR: EVTRADE_DB_URL not set", file=sys.stderr); sys.exit(1)
    with open(SCHEMA_YML, "r", encoding="utf-8") as f:
        schema = parse_yaml(f.read())
    engine = create_engine(DATABASE_URL, pool_size=1, pool_pre_ping=True)
    insp = inspect(engine)
    db_tables = set(insp.get_table_names()) - {"alembic_version"}
    yml_tables = set(schema.get("tables", {}).keys())
    diff = False
    if yml_tables - db_tables:
        print(f"Tables to ADD: {', '.join(sorted(yml_tables - db_tables))}"); diff = True
    if db_tables - yml_tables:
        print(f"Tables to REMOVE: {', '.join(sorted(db_tables - yml_tables))}"); diff = True
    for tn in sorted(yml_tables & db_tables):
        yc = set(schema["tables"][tn].get("columns", {}).keys())
        dc = {c["name"] for c in insp.get_columns(tn)}
        if yc - dc:
            print(f"{tn}: ADD columns {', '.join(sorted(yc - dc))}"); diff = True
        if dc - yc:
            print(f"{tn}: REMOVE columns {', '.join(sorted(dc - yc))}"); diff = True
        for cn in sorted(yc & dc):
            cd = schema["tables"][tn]["columns"][cn]
            if not isinstance(cd, dict):
                continue
            db_col = next((c for c in insp.get_columns(tn) if c["name"] == cn), None)
            if not db_col:
                continue
            yb = yaml_to_mysql_base(cd.get("type", ""))
            db_raw = str(db_col["type"]).lower()
            # Strip collation info
            for sep in (" collate", "COLLATE"):
                if sep in db_raw:
                    db_raw = db_raw[:db_raw.index(sep)]
            db = db_raw[:db_raw.index('(')] if '(' in db_raw else db_raw
            # Normalize DB type to match yaml_to_mysql_base output
            db_norm = {"int": "integer", "tinyint": "tinyint"}.get(db, db)
            if yb != db_norm:
                print(f"{tn}.{cn}: type {db} -> {yb}"); diff = True
            if cd.get("nullable", True) != db_col["nullable"]:
                print(f"{tn}.{cn}: nullable change"); diff = True
    if not diff:
        print("No differences — schema.yml matches live DB.")
    else:
        print("\nRun: python scripts/sync_schema.py apply")
    engine.dispose()


def main():
    ap = argparse.ArgumentParser(description="Unified Schema Manager")
    ap.add_argument("command", choices=["export", "diff", "apply"])
    {"export": export_schema, "diff": diff_schema, "apply": apply_schema}[ap.parse_args().command]()

if __name__ == "__main__":
    main()
