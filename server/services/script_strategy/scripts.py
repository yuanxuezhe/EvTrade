"""
server/services/script_strategy/scripts.py — Script CRUD（直接读写 strategy_script 表）

复合主键 (user_id, id)：id = 用户自命名 (通常 = name)。
- 可见范围: 用户看自己的 + is_public=1 公开的; admin 看全部
- 删除级联: 先删引用该 script 的 strategy_task (FK 严格约束), 再删 script

运行时（回测/实盘）不在此处 — 已迁移到独立服务 strategy_exec (2026-08-09)。
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from server.services.script_strategy._convert import (
    json_dumps,
    script_row_to_dict,
)


def list_scripts(
    user_id: int, is_admin: bool = False,
    name: Optional[str] = None, status: Optional[str] = None,
    only_mine: bool = False,
) -> List[Dict[str, Any]]:
    """列脚本 (admin 看所有, 用户看自己的 + 公开的)

    Args:
        name: 模糊匹配 name (前端搜索框用)
        status: 过滤 (active/archived)
        only_mine: True 时只列自己的 (前端"我的脚本" tab)
    """
    from server.tables import StrategyScript
    if is_admin:
        rows = StrategyScript.query_all(order="desc")
    elif only_mine:
        rows = StrategyScript.query_by_fields({"user_id": user_id})
        rows.sort(key=lambda r: getattr(r, "_data", {}).get("id", ""), reverse=True)
    else:
        mine = StrategyScript.query_by_fields({"user_id": user_id})
        public = StrategyScript.query_by_fields({"is_public": 1})
        seen = set()
        rows = []
        for r in mine + public:
            key = (r._data.get("user_id"), r._data.get("id"))
            if key not in seen:
                seen.add(key)
                rows.append(r)
        rows.sort(key=lambda r: (
            0 if r._data.get("user_id") == user_id else 1,  # 自己的排前
            r._data.get("id", ""),
        ))
    out = []
    for r in rows:
        d = script_row_to_dict(r)
        if name and name.lower() not in d.get("name", "").lower():
            continue
        if status and d.get("status") != status:
            continue
        out.append(d)
    return out


def get_script(script_id: str, user_id: int, is_admin: bool = False) -> Optional[Dict[str, Any]]:
    """按 (user_id, id) 取脚本 (v90+ 复合 PK): 用户优先自己的, 否则公开的"""
    from server.tables import StrategyScript
    row = StrategyScript.query_one(user_id=user_id, id=script_id)
    if row is not None:
        return script_row_to_dict(row)
    if is_admin:
        candidates = StrategyScript.query_by_fields({"id": script_id})
    else:
        candidates = StrategyScript.query_by_fields({"id": script_id, "is_public": 1})
    if candidates:
        return script_row_to_dict(candidates[0])
    return None


def get_script_by_name(name: str, user_id: int, is_admin: bool = False) -> Optional[Dict[str, Any]]:
    """按 name 查脚本 (admin 跨用户, 用户仅自己的); 优先 active 中最新"""
    from server.tables import StrategyScript
    if is_admin:
        rows = StrategyScript.query_by_fields({"name": name})
    else:
        rows = StrategyScript.query_by_fields({"user_id": user_id, "name": name})
    if not rows:
        return None
    rows.sort(key=lambda r: (
        0 if getattr(r, "_data", {}).get("status") == "active" else 1,
        -getattr(r, "_data", {}).get("id", 0),
    ))
    return script_row_to_dict(rows[0])


def create_script(
    user_id: int, name: str, code: str, params_schema: List[Dict[str, Any]],
    description: str = "",
    is_public: bool = False,
) -> Dict[str, Any]:
    """创建脚本 (v90+ 复合 PK; id 默认 = name, 同用户内唯一)"""
    from server.tables import StrategyScript
    existing = StrategyScript.query_one(user_id=user_id, id=name)
    if existing is not None:
        raise ValueError(f"脚本名已存在: {name!r}")
    now = datetime.now()
    data = {
        "user_id": user_id,
        "id": name,
        "name": name,
        "code": code,
        "params_schema": json_dumps(params_schema),
        "description": description,
        "status": "active",
        "is_public": 1 if is_public else 0,
        "created_at": now,
        "updated_at": now,
    }
    try:
        row = StrategyScript.add_one(data)
    except Exception as e:
        if "Duplicate" in str(e):
            raise ValueError(f"脚本名已存在: {name!r}") from e
        raise
    return script_row_to_dict(row)


def update_script(
    script_id: str, user_id: int, is_admin: bool, patch: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """更新脚本 (v90+ 复合 PK = (user_id, id))"""
    from server.tables import StrategyScript
    row = StrategyScript.query_one(user_id=user_id, id=script_id)
    if row is None:
        if is_admin:
            candidates = StrategyScript.query_by_fields({"id": script_id})
            if not candidates:
                return None
            row = candidates[0]
            actual_user_id = row._data.get("user_id")
        else:
            return None
    else:
        actual_user_id = user_id

    update_data = {}
    for k in ("code", "description", "status", "is_public", "name"):
        if k in patch:
            update_data[k] = patch[k]
    if "params_schema" in patch:
        update_data["params_schema"] = json_dumps(patch["params_schema"])
    if update_data:
        update_data["updated_at"] = datetime.now()
        StrategyScript.upsert_one(update_data, user_id=actual_user_id, id=script_id)
    return get_script(script_id, actual_user_id, is_admin)


def delete_script(script_id: str, user_id: int, is_admin: bool) -> bool:
    """删除脚本 (v90+ 复合 PK). 级联: task → strategy → script。

    v123 任务不再直接挂 script_id, 需先删引用该脚本的策略 (及其 task),
    再删脚本本身。策略的 task 一并删除 (FK 严格约束)。

    📌 新架构 (strategy_exec 独立服务): 不再本地停实盘任务 —
       正在 strategy_exec 跑的任务由该服务管理, 这里仅做本地 DB 行清理。
    """
    from server.tables import StrategyScript, StrategyTask, Strategy
    row = StrategyScript.query_one(user_id=user_id, id=script_id)
    if row is None:
        return False
    if not is_admin and getattr(row, "_data", {}).get("user_id") != user_id:
        return False
    strategies = Strategy.query_by_fields({"user_id": user_id, "script_id": script_id})
    for strat in strategies:
        sid = strat._data.get("strategy_id")
        for task in StrategyTask.query_by_fields({"user_id": user_id, "strategy_id": sid}, columns=["id"]):
            StrategyTask.delete_one(id=task._data.get("id"))
        Strategy.delete_one(strategy_id=sid)
    return StrategyScript.delete_one(user_id=user_id, id=script_id)
