"""
server/services/script_strategy/tasks.py — Task CRUD + 信号/审计读取

任务创建仍在 EvTrade (直接读写 strategy_task 表); 运行/停止已转发到
独立服务 strategy_exec,
本模块不启动任何引擎线程。
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from server.services.script_strategy._convert import (
    json_dumps,
    json_loads,
    task_row_to_dict,
    audit_row_to_dict,
    TASK_LIST_COLUMNS,
)


def list_tasks(
    user_id: int, is_admin: bool = False, status: Optional[str] = None,
    mode: Optional[str] = None,
    strategy_id: Optional[int] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """列 task (含 filter)

    filter:
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
    # 轻量列: 列表不拖回 backtest_result 大 blob (防 MySQL 1038 / 响应膨胀)
    if filters:
        rows = StrategyTask.query_by_fields(filters, columns=TASK_LIST_COLUMNS)
    else:
        rows = StrategyTask.query_by_fields({}, order="desc", columns=TASK_LIST_COLUMNS)
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
    status: str = "queued",  # 状态机: queued → running → finished / failed / stopped / abandoned
    metric: Optional[str] = None,  # 批次排序指标 (sweep top1 选择, 重测还原用)
) -> Dict[str, Any]:
    """创建任务 (挂 strategy_id, 可带 batch_no).

    创建不立即执行; 由 backtest/retest 端点转发 strategy_exec 后异步运行。
    批次任务由 batches.create_backtest_batch 复用本函数。

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
        "mode": mode,            # 创建时即定 mode (纯回测: 仅 backtest)
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
        "metric": metric,
        "created_at": now,
        "updated_at": now,
    }
    row = StrategyTask.add_one(data)
    task_id = getattr(row, "_data", {}).get("id")
    return get_task(task_id, user_id, is_admin=True)


def create_tasks_batch(
    user_id: int,
    strategy_id: int,
    stock_code: str,
    combos: List[Dict[str, Any]],
    *,
    description: str = "",
    backtest_start_date: Optional[str] = None,
    backtest_end_date: Optional[str] = None,
    period: Optional[str] = None,
    fields: Optional[str] = None,
    mode: str = "backtest",
    batch_no: Optional[int] = None,
    status: str = "queued",
    metric: Optional[str] = None,
) -> List[int]:
    """批量创建 task (sweep 一次 N 行) — executemany 单往返, 替代逐行 create_task。

    change 2026-08-30-sweep-worker-queue: sweep 对 N 组合逐行 create_task = ~2N 次串行
    DB 往返 (Strategy SELECT + INSERT), 大扫描吃满前端 15s 超时。改为:
    - Strategy 权限校验只查 1 次 (循环外)
    - N 行 INSERT 走 executemany (单 session, 单往返)
    - 回填 id 用 `WHERE batch_no=? AND strategy_id=? ORDER BY id` (同批次连续自增, 顺序稳定)

    Args: 同 create_task, 但 `combos` = 参数 dict 列表 (每 1 个 = 1 行 task)。
    Returns: task id 列表 (按 combos 顺序, 长度 = len(combos))。
    Raises: ValueError: 策略不存在 / 权限 / combos 为空。
    """
    from server.tables import Strategy
    from server.tables.base import get_engine
    from sqlalchemy import text

    strat = Strategy.query_one(strategy_id=strategy_id)
    if strat is None:
        raise ValueError(f"strategy_id {strategy_id} 不存在")
    if getattr(strat, "_data", {}).get("user_id") != user_id:
        raise ValueError(f"strategy_id {strategy_id} 不属于 user_id={user_id}")
    if not combos:
        raise ValueError("create_tasks_batch: combos 不能为空")

    now = datetime.now()
    rows = []
    for c in combos:
        rows.append({
            "user_id": user_id,
            "strategy_id": strategy_id,
            "batch_no": batch_no,
            "description": description,
            "stock_code": stock_code,
            "mode": mode,
            "status": status,
            "params": json_dumps(c),
            "period": period or "1d",
            "fields": fields or "open,close,high,low",
            "pnl": 0.0,
            "trades_count": 0,
            "started_at": None,
            "finished_at": None,
            "backtest_start_date": backtest_start_date,
            "backtest_end_date": backtest_end_date,
            "metric": metric,
            "created_at": now,
            "updated_at": now,
        })

    cols = list(rows[0].keys())
    col_list = ", ".join(f"`{c}`" for c in cols)
    val_list = ", ".join(f":{c}" for c in cols)
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text(f"INSERT INTO `strategy_task` ({col_list}) VALUES ({val_list})"), rows)
        # 回填 id: 同批次连续自增, 按 id 升序 = combos 顺序
        r = conn.execute(text(
            "SELECT id FROM strategy_task "
            "WHERE strategy_id=:sid AND batch_no=:bn ORDER BY id"
        ), {"sid": strategy_id, "bn": batch_no}).mappings().all()
    ids = [row["id"] for row in r]
    if len(ids) != len(combos):
        raise ValueError(
            f"create_tasks_batch: 回填 {len(ids)} id != combos {len(combos)} (batch_no={batch_no})"
        )
    return ids



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
