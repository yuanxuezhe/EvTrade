"""
strategy_exec.data_access.strategy_script — 读 strategy_script 表

📌 strategy_exec 只读 (EvTrade 是唯一写方, 见 strategy-exec/spec.md REQ-SE-005)
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from strategy_exec.data_access.db import get_session


def _json_loads(v: Any, default=None):
    if v is None or v == "":
        return default
    if isinstance(v, (list, dict)):
        return v
    try:
        return json.loads(v)
    except (ValueError, TypeError):
        return default


def get_script(user_id: int, script_id: str) -> Optional[Dict[str, Any]]:
    """按 (user_id, id) 复合 PK 查脚本

    Returns:
        {id, user_id, name, code, params_schema, description, status, is_public}
        或 None (不存在)
    """
    with get_session() as session:
        row = session.execute(
            text("""
                SELECT id, user_id, name, code, params_schema, description, status, is_public
                  FROM strategy_script
                 WHERE user_id = :u AND id = :i
                 LIMIT 1
            """),
            {"u": user_id, "i": script_id},
        ).mappings().first()
        if row is None:
            return None
        return {
            "id": row["id"],
            "user_id": row["user_id"],
            "name": row["name"],
            "code": row["code"],
            "params_schema": _json_loads(row["params_schema"], default=[]),
            "description": row["description"] or "",
            "status": row["status"],
            "is_public": bool(row["is_public"]),
        }


def get_public_script_by_id(script_id: str) -> Optional[Dict[str, Any]]:
    """按 id 查公开脚本 (跨用户)

    Returns: 同 get_script, 或 None (无匹配公开脚本)
    """
    with get_session() as session:
        row = session.execute(
            text("""
                SELECT id, user_id, name, code, params_schema, description, status, is_public
                  FROM strategy_script
                 WHERE id = :i AND is_public = 1
                 LIMIT 1
            """),
            {"i": script_id},
        ).mappings().first()
        if row is None:
            return None
        return {
            "id": row["id"],
            "user_id": row["user_id"],
            "name": row["name"],
            "code": row["code"],
            "params_schema": _json_loads(row["params_schema"], default=[]),
            "description": row["description"] or "",
            "status": row["status"],
            "is_public": bool(row["is_public"]),
        }


def list_scripts(user_id: int, include_public: bool = True) -> List[Dict[str, Any]]:
    """列脚本: 自己的 + 可选公开的"""
    if include_public:
        sql = """
            SELECT id, user_id, name, code, params_schema, description, status, is_public
              FROM strategy_script
             WHERE user_id = :u OR is_public = 1
             ORDER BY user_id = :u DESC, id
        """
    else:
        sql = """
            SELECT id, user_id, name, code, params_schema, description, status, is_public
              FROM strategy_script
             WHERE user_id = :u
             ORDER BY id
        """
    with get_session() as session:
        rows = session.execute(text(sql), {"u": user_id}).mappings().all()
        return [
            {
                "id": r["id"],
                "user_id": r["user_id"],
                "name": r["name"],
                "code": r["code"],
                "params_schema": _json_loads(r["params_schema"], default=[]),
                "description": r["description"] or "",
                "status": r["status"],
                "is_public": bool(r["is_public"]),
            }
            for r in rows
        ]