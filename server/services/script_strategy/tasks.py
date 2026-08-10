"""
server/services/script_strategy/tasks.py — Task CRUD + 信号/审计读取

任务创建仍在 EvTrade (直接读写 strategy_task 表); 运行/停止已转发到
独立服务 strategy_exec (2026-08-09), 本模块不启动任何引擎线程。
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from server.services.script_strategy._convert import (
    json_dumps,
    json_loads,
    task_row_to_dict,
    audit_row_to_dict,
)


def list_tasks(
    user_id: int, is_admin: bool = False, status: Optional[str] = None,
    mode: Optional[str] = None,
    strategy_id: Optional[int] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """列 task (含 filter)

    v123 filter:
    - strategy_id: 限定策略
    - limit: 默认 50, 上限 200 (endpoint 层强制)
    """
    from server.tables import StrategyTask
    filters: Dict[str, Any] = {}
    if not is_admin:
        filters["user_id"] = user_id
    if status:
        filters["status"] = status
    if mode:
        filters["mode"] = mode
    if strategy_id:
        filters["strategy_id"] = strategy_id
    if filters:
        rows = StrategyTask.query_by_fields(filters)
    else:
        rows = StrategyTask.query_all(order="desc")
        rows.sort(key=lambda r: getattr(r, "_data", {}).get("id", 0), reverse=True)
    # limit 截断
    rows = list(rows)[:limit]
    return [task_row_to_dict(r) for r in rows]


def get_task(task_id: int, user_id: int, is_admin: bool = False) -> Optional[Dict[str, Any]]:
    from server.tables import StrategyTask
    row = StrategyTask.query_one(id=task_id)
    if row is None:
        return None
    if not is_admin and getattr(row, "_data", {}).get("user_id") != user_id:
        return None
    return task_row_to_dict(row)


def create_task(
    user_id: int,
    strategy_id: int,
    stock_code: str,
    params: Dict[str, Any],
    *,
    description: str = "",
    backtest_start_date: Optional[str] = None,
    backtest_end_date: Optional[str] = None,
    period: Optional[str] = None,
    fields: Optional[str] = None,
    mode: Optional[str] = None,
    batch_no: Optional[int] = None,
    status: str = "created",
) -> Dict[str, Any]:
    """创建任务 (v123: 挂 strategy_id, 可带 batch_no).

    创建不立即执行; 由 backtest/live 端点转发 strategy_exec 后异步运行。
    批次任务由 strategies.create_backtest_batch / create_live_batch 复用本函数。

    Raises:
        ValueError: 策略不存在 / 权限
    """
    from server.tables import StrategyTask, Strategy
    strat = Strategy.query_one(strategy_id=strategy_id)
    if strat is None:
        raise ValueError(f"strategy_id {strategy_id} 不存在")
    if getattr(strat, "_data", {}).get("user_id") != user_id:
        raise ValueError(f"strategy_id {strategy_id} 不属于 user_id={user_id}")

    now = datetime.now()
    data = {
        "user_id": user_id,
        "strategy_id": strategy_id,
        "batch_no": batch_no,
        "description": description,
        "stock_code": stock_code,
        "mode": mode,            # 创建时即定 mode (backtest/live 由 batch 语义决定)
        "status": status,
        "params": json_dumps(params),
        "period": period or "1d",
        "fields": fields or "open,close,high,low",  # 默认 OHLC, 用户可改
        "pnl": 0.0,
        "trades_count": 0,
        "started_at": None,
        "finished_at": None,
        "backtest_start_date": backtest_start_date,
        "backtest_end_date": backtest_end_date,
        "created_at": now,
        "updated_at": now,
    }
    row = StrategyTask.add_one(data)
    task_id = getattr(row, "_data", {}).get("id")
    return get_task(task_id, user_id, is_admin=True)


def delete_task(task_id: int, user_id: int, is_admin: bool = False) -> bool:
    from server.tables import StrategyTask
    row = StrategyTask.query_one(id=task_id)
    if row is None:
        return False
    if not is_admin and getattr(row, "_data", {}).get("user_id") != user_id:
        return False
    return StrategyTask.delete_one(id=task_id)


def get_task_logs(task_id: int, user_id: int, is_admin: bool = False) -> Optional[Dict[str, Any]]:
    """返 task 详情 + (回测模式) audit_log + (实盘模式) 当前状态"""
    t = get_task(task_id, user_id, is_admin)
    if t is None:
        return None
    if t.get("mode") == "backtest":
        # 交易明细在 backtest_result.best.trades (引擎契约)
        logs = ((t.get("backtest_result") or {}).get("best") or {}).get("trades", []) if t.get("backtest_result") else []
    else:
        logs = []
    return {**t, "logs": logs}


def _extract_signals_and_progress(mode, row_data):
    """按 mode 从 task 行提取 (signals, progress) — 详情面板时间轴用"""
    if mode == "backtest":
        result = json_loads(row_data.get("backtest_result"))
        best = (result or {}).get("best", {}) if result else {}
        return best.get("signal_log", []), best.get("progress_log", [])
    if mode == "live":
        return json_loads(row_data.get("live_signals"), default=[]), []
    return [], []


def get_task_signals(
    task_id: int, user_id: int, is_admin: bool = False,
    type_filter: Optional[str] = None, limit: int = 500,
) -> Optional[Dict[str, Any]]:
    """返 task 信号流 + 进度时间轴 (用于详情面板)

    Returns:
        dict {mode, signals, progress, total_signals, truncated} or None
    """
    from server.tables import StrategyTask
    row = StrategyTask.query_one(id=task_id)
    if row is None:
        return None
    if not is_admin and getattr(row, "_data", {}).get("user_id") != user_id:
        return None

    row_data = getattr(row, "_data", {})
    mode = row_data.get("mode")
    signals, progress = _extract_signals_and_progress(mode, row_data)

    if type_filter:
        # 信号对象统一字段是 signal_type (strategy_exec backtest/live 一致)
        signals = [s for s in signals if s.get("signal_type") == type_filter]

    total_signals = len(signals)
    signals = signals[-limit:] if limit > 0 else signals
    return {
        "mode": mode,
        "signals": signals,
        "progress": progress[-limit:] if progress and limit > 0 else progress,
        "total_signals": total_signals,
        "truncated": total_signals > len(signals),
    }


def get_task_audit(
    task_id: int, user_id: int, is_admin: bool = False,
    trigger_type: Optional[str] = None,
    trd_date: Optional[str] = None,
    limit: int = 500,
) -> Optional[Dict[str, Any]]:
    """返 task 永久 audit (从 strategy_script_audit 表, 不限条数)

    Returns:
        dict {audit, total, truncated} or None
    """
    from server.tables import StrategyTask, StrategyScriptAudit
    task_row = StrategyTask.query_one(id=task_id)
    if task_row is None:
        return None
    if not is_admin and getattr(task_row, "_data", {}).get("user_id") != user_id:
        return None

    filters: Dict[str, Any] = {"task_id": task_id}
    if trigger_type:
        filters["trigger_type"] = trigger_type
    if trd_date:
        filters["trd_date"] = trd_date

    rows = StrategyScriptAudit.query_by_fields(filters)
    rows.sort(key=lambda r: getattr(r, "_data", {}).get("id", 0))
    audit_list = [audit_row_to_dict(r) for r in rows]

    total = len(audit_list)
    if limit > 0:
        truncated = total > limit
        audit_list = audit_list[-limit:]
    else:
        truncated = False
    return {"audit": audit_list, "total": total, "truncated": truncated}
