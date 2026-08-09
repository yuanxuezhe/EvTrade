"""
server/services/script_strategy/_convert.py — TableBase Row ↔ API dict 转换

职责单一: 把 strategy_script / strategy_task / strategy_script_audit 的行
转成 API 返回用的 dict (幂等, 无 DB 写入, 无外部副作用)。
"""
import json
from datetime import datetime
from typing import Any, Dict, Optional


def json_dumps(v: Any) -> Any:
    """序列化 JSON 字段; None 原样返 (避免把 NULL 存成字符串 'null')"""
    return json.dumps(v, ensure_ascii=False) if v is not None else None


def json_loads(v: Any, default=None):
    """反序列化 JSON 字段; 已是 dict/list 直接返, 空/坏值用 default"""
    if v is None or v == "":
        return default
    if isinstance(v, (list, dict)):
        return v
    try:
        return json.loads(v)
    except (ValueError, TypeError):
        return default


def iso(v) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, str):
        return v
    return str(v)


def script_row_to_dict(row) -> Dict[str, Any]:
    d = getattr(row, "_data", {})
    return {
        "id": d.get("id"),  # v90+ str (用户自命名)
        "user_id": d.get("user_id"),
        "name": d.get("name", ""),
        "code": d.get("code", ""),
        "params_schema": json_loads(d.get("params_schema"), default=[]),
        "description": d.get("description", ""),
        "status": d.get("status", "active"),
        "is_public": bool(d.get("is_public", 0)),  # v90+
        "created_at": iso(d.get("created_at")),
        "updated_at": iso(d.get("updated_at")),
    }


def task_row_to_dict(row) -> Dict[str, Any]:
    d = getattr(row, "_data", {})
    return {
        "id": d.get("id"),
        "user_id": d.get("user_id"),
        "script_id": d.get("script_id"),
        "stock_code": d.get("stock_code", ""),
        "mode": d.get("mode"),
        "status": d.get("status", ""),
        "params": json_loads(d.get("params"), default={}),
        "backtest_result": json_loads(d.get("backtest_result")),
        "best_params": json_loads(d.get("best_params")),
        "backtest_start_date": d.get("backtest_start_date"),
        "backtest_end_date": d.get("backtest_end_date"),
        "period": d.get("period"),
        "fields": d.get("fields"),
        "pnl": d.get("pnl", 0.0) or 0.0,
        "positions": json_loads(d.get("positions"), default={}),
        "trades_count": d.get("trades_count", 0) or 0,
        "live_signals": json_loads(d.get("live_signals"), default=[]),
        "progress": json_loads(d.get("progress"), default=None),
        "started_at": iso(d.get("started_at")),
        "finished_at": iso(d.get("finished_at")),
        "error_msg": d.get("error_msg"),
        "created_at": iso(d.get("created_at")),
        "updated_at": iso(d.get("updated_at")),
    }


def audit_row_to_dict(row) -> Dict[str, Any]:
    d = getattr(row, "_data", {})
    return {
        "id": d.get("id"),
        "task_id": d.get("task_id"),
        "stime": d.get("stime"),
        "trd_date": d.get("trd_date"),
        "phase": d.get("phase"),
        "trigger_type": d.get("trigger_type"),
        "stock_code": d.get("stock_code"),
        "price": d.get("price"),
        "volume": d.get("volume"),
        "indicators": json_loads(d.get("indicators"), default={}),
        "state": json_loads(d.get("state"), default={}),
        "msg": d.get("msg"),
        "order_no": d.get("order_no"),
        "payload": json_loads(d.get("payload"), default={}),
        "created_at": iso(d.get("created_at")),
    }
