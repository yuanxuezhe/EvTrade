"""
server/services/script_strategy/strategies.py — 策略 CRUD

职责单一: Strategy 实体 CRUD; 可见性判定委托 access.py (显式 is_public)。
- 建策略必填 {name, script_id, stock_code} (绑定标的), 不填参数、不定模式
- 回测批次 / 实盘门禁在 batches.py; param_ranges 展开在 params.py; 错误类型在 errors.py

外部兼容: `from ...strategies import StrategyError` 仍可用 (re-export)。
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from server.services.script_strategy._convert import (
    script_row_to_dict,
    strategy_row_to_dict,
)
from server.services.script_strategy.errors import StrategyError
from server.services.script_strategy.access import public_view


def _resolve_script(owner_user_id: int, script_id: str) -> Optional[Dict[str, Any]]:
    """解析策略所属脚本: 先 (owner, script_id), 再公开脚本兜底"""
    from server.tables import StrategyScript
    row = StrategyScript.query_one(user_id=owner_user_id, id=script_id)
    if row is not None:
        return script_row_to_dict(row)
    public = StrategyScript.query_by_fields({"id": script_id, "is_public": 1})
    if public:
        return script_row_to_dict(public[0])
    return None


def list_strategies(
    user_id: int, is_admin: bool = False,
    status: Optional[str] = None, only_mine: bool = False,
) -> List[Dict[str, Any]]:
    """列策略: 自己的 (全量) + 他人公开的 (精简视图); admin 看全部 (全量)."""
    from server.tables import Strategy
    if is_admin:
        rows = Strategy.query_all(order="desc")
    else:
        rows = Strategy.query_by_fields({"user_id": user_id})
        if not only_mine:
            for r in Strategy.query_by_fields({"is_public": 1}):
                if r._data.get("user_id") != user_id:
                    rows.append(r)
        rows.sort(key=lambda r: getattr(r, "_data", {}).get("strategy_id", 0), reverse=True)
    out = []
    for r in rows:
        d = strategy_row_to_dict(r)
        if status and d.get("status") != status:
            continue
        if not is_admin and d.get("user_id") != user_id:
            out.append(public_view(r))   # 他人公开策略 → 精简
        else:
            out.append(d)
    return out


def get_strategy(strategy_id: int, user_id: int, is_admin: bool = False) -> Optional[Dict[str, Any]]:
    """策略详情: owner/admin 返回完整 (含脚本); 他人公开返回精简视图; 他人私有/不存在 → None."""
    from server.services.script_strategy.access import resolve_strategy
    row = resolve_strategy(strategy_id, user_id, is_admin=is_admin)
    if row is None:
        return None
    d = strategy_row_to_dict(row)
    if not is_admin and d.get("user_id") != user_id:
        return public_view(row)   # 他人公开策略 → 精简视图 (无 script/best_params)
    d["script"] = _resolve_script(d.get("user_id"), d.get("script_id"))
    return d


def create_strategy(user_id: int, name: str, script_id: str, stock_code: str) -> Dict[str, Any]:
    """创建策略 (必须绑定标的 stock_code, 只针对此标的回测).

    Raises:
        StrategyError: MISSING_STOCK / NO_SCRIPT
    """
    if not stock_code or not stock_code.strip():
        raise StrategyError("MISSING_STOCK", "新建策略必须指定标的 stock_code")
    from server.tables import Strategy
    from server.services.script_strategy.scripts import get_script
    script = get_script(script_id, user_id, is_admin=False)
    if script is None:
        raise StrategyError("NO_SCRIPT", f"script_id {script_id} 不存在或不可用")
    now = datetime.now()
    data = {
        "user_id": user_id,
        "script_id": script_id,
        "name": name,
        "status": "draft",
        "is_public": 0,
        "stock_code": stock_code.strip(),
        "best_params": None,
        "created_at": now,
        "updated_at": now,
    }
    row = Strategy.add_one(data)
    return strategy_row_to_dict(row)


def update_strategy(
    strategy_id: int, user_id: int, is_admin: bool, patch: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """更新策略 (仅 user_id=me; 可改 name / status)"""
    from server.tables import Strategy
    row = Strategy.query_one(strategy_id=strategy_id)
    if row is None:
        return None
    if not is_admin and getattr(row, "_data", {}).get("user_id") != user_id:
        return None
    update_data = {}
    for k in ("name", "status"):
        if k in patch and patch[k] is not None:
            update_data[k] = patch[k]
    if "is_public" in patch and patch["is_public"] is not None:
        update_data["is_public"] = 1 if patch["is_public"] else 0
    if update_data:
        update_data["updated_at"] = datetime.now()
        Strategy.update_one(update_data, strategy_id=strategy_id)
    return strategy_row_to_dict(Strategy.query_one(strategy_id=strategy_id))


def delete_strategy(strategy_id: int, user_id: int, is_admin: bool) -> bool:
    """删除策略 (级联删其 task)"""
    from server.tables import Strategy, StrategyTask
    row = Strategy.query_one(strategy_id=strategy_id)
    if row is None:
        return False
    if not is_admin and getattr(row, "_data", {}).get("user_id") != user_id:
        return False
    for task in StrategyTask.query_by_fields({"strategy_id": strategy_id}, columns=["id"]):
        StrategyTask.delete_one(id=task._data.get("id"))
    return Strategy.delete_one(strategy_id=strategy_id)


__all__ = [
    "StrategyError",
    "list_strategies", "get_strategy", "create_strategy",
    "update_strategy", "delete_strategy",
]
