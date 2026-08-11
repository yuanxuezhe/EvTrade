"""
server/services/script_strategy/_convert.py — TableBase Row ↔ API dict 转换

职责单一: 把 strategy / strategy_script / strategy_task / strategy_script_audit 的行
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


def strategy_row_to_dict(row) -> Dict[str, Any]:
    d = getattr(row, "_data", {})
    return {
        "strategy_id": d.get("strategy_id"),
        "user_id": d.get("user_id"),
        "script_id": d.get("script_id"),
        "name": d.get("name", ""),
        "status": d.get("status", "draft"),
        "is_public": bool(d.get("is_public", 0)),  # v125 显式可见性
        "stock_code": d.get("stock_code"),          # v125 绑定标的
        "best_params": json_loads(d.get("best_params")),
        "created_at": iso(d.get("created_at")),
        "updated_at": iso(d.get("updated_at")),
    }


# 列表接口轻量列白名单 (query_by_fields(columns=...) 用).
# 排除大 BLOB/JSON 列: backtest_result / positions / live_signals / progress
# 仅在详情 (query_one 全列) 返回。列表 SELECT * + ORDER BY 拖回最大 1.85MB 的
# backtest_result 会让 MySQL filesort 超大行报 1038 'Out of sort memory' → 500。
TASK_LIST_COLUMNS = (
    "id", "user_id", "strategy_id", "batch_no", "description",
    "stock_code", "mode", "status", "params",
    "backtest_start_date", "backtest_end_date", "period", "fields",
    "pnl", "trades_count", "backtest_metric_value", "metric",
    "started_at", "finished_at", "error_msg",
    "created_at", "updated_at", "execution_service", "execution_pid", "version",
)


def _row_metric_value(d: Dict[str, Any]) -> Optional[float]:
    """行指标值: 列优先, 老行/未回填回退解析 backtest_result blob."""
    mv = d.get("backtest_metric_value")
    if mv is not None:
        try:
            return float(mv)
        except (TypeError, ValueError):
            return None
    return _extract_metric_value(json_loads(d.get("backtest_result")))


def task_row_to_dict(row) -> Dict[str, Any]:
    d = getattr(row, "_data", {})
    return {
        "id": d.get("id"),
        "user_id": d.get("user_id"),
        "strategy_id": d.get("strategy_id"),
        "batch_no": d.get("batch_no"),
        "description": d.get("description", ""),
        "stock_code": d.get("stock_code", ""),
        "mode": d.get("mode"),
        "status": d.get("status", ""),
        "params": json_loads(d.get("params"), default={}),
        "backtest_result": json_loads(d.get("backtest_result")),
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
        "backtest_metric_value": _row_metric_value(d),
        "metric": d.get("metric") or "sharpe",
    }


def _extract_metric_value(backtest_result: Optional[Dict[str, Any]], metric: str = "sharpe") -> Optional[float]:
    """从 backtest_result 提取 metric_value (前端展示 + 批次 best 排序用).

    v123 移除了 sweep summary task, 每行 task 直接携带自身 backtest_result:
    - 优先所选 metric 字段 (sharpe/total_return/calmar)
    - 回退 sharpe → total_return → pnl/initial_cash
    """
    if not backtest_result or not isinstance(backtest_result, dict):
        return None
    if metric in backtest_result:
        try:
            return float(backtest_result[metric])
        except (TypeError, ValueError):
            pass
    for key in ("sharpe", "total_return"):
        if backtest_result.get(key) is not None:
            try:
                return float(backtest_result[key])
            except (TypeError, ValueError):
                pass
    # 回退到 pnl / initial_cash
    pnl = backtest_result.get("pnl")
    cash = backtest_result.get("initial_cash") or 100000.0
    if pnl is not None and cash:
        try:
            return float(pnl) / float(cash)
        except (TypeError, ValueError):
            pass
    return None


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
