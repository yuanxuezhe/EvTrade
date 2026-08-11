"""
server/services/script_strategy/strategy_order_convert.py — strategy_order Row → API dict

职责单一: 母单行转 API 返回 dict (仿 _convert.py task_row_to_dict 模式)。
时间字段走 iso() 序列化, 与既有 strategy / task 输出一致。
"""
from typing import Any, Dict

from server.services.script_strategy._convert import iso


def strategy_order_row_to_dict(row) -> Dict[str, Any]:
    d = getattr(row, "_data", {})
    return {
        "id": d.get("id"),
        "task_id": d.get("task_id"),
        "user_id": d.get("user_id"),
        "strategy_id": d.get("strategy_id"),
        "stock_code": d.get("stock_code", ""),
        "status": d.get("status", "stopped"),
        "active_task_id": d.get("active_task_id"),
        "run_count": d.get("run_count", 0) or 0,
        "last_started_at": iso(d.get("last_started_at")),
        "last_stopped_at": iso(d.get("last_stopped_at")),
        "closed_at": iso(d.get("closed_at")),
        "created_at": iso(d.get("created_at")),
        "updated_at": iso(d.get("updated_at")),
    }


__all__ = ["strategy_order_row_to_dict"]
