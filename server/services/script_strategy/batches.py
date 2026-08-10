"""
server/services/script_strategy/batches.py — 回测/实盘批次 + 聚合查询 (v123)

职责单一: 围绕 `strategy_task` 的批次操作。
- create_backtest_batch: 单次=1 行 task, 扫描=param_ranges 展开 N 行 task, 统一 task_batch 序号
- create_live_batch: best_params 门禁, 建 1 行 live task
- list_batches / list_batch_tasks: 虚拟 GROUP BY batch_no 聚合 (无批头表)

不执行运行时; 由 api 层转发 strategy_exec, 完成后 strategy_exec 回写 best_params。
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from server.repo.orders import next_seq
from server.services.script_strategy._convert import (
    iso,
    json_loads,
    task_row_to_dict,
    _extract_metric_value,
)
from server.services.script_strategy.errors import StrategyError
from server.services.script_strategy.params import expand_param_ranges, validate_params_keys
from server.services.script_strategy.strategies import (
    _resolve_script,
    _strategy_public_derived,
)
from server.services.script_strategy.tasks import create_task


def _require_owned_strategy(strategy_id: int, user_id: int, is_admin: bool = False):
    """取策略行; 不存在/非本人(且非 admin 派生公开) 返回 None, 否则返回 Strategy row."""
    from server.tables import Strategy
    strat = Strategy.query_one(strategy_id=strategy_id)
    if strat is None:
        return None
    if not is_admin and getattr(strat, "_data", {}).get("user_id") != user_id \
            and not _strategy_public_derived(strat):
        return None
    return strat


def create_backtest_batch(
    user_id: int,
    strategy_id: int,
    *,
    mode: str,  # 'single' | 'sweep'
    stock_code: str,
    backtest_start_date: str,
    backtest_end_date: str,
    params: Optional[Dict[str, Any]] = None,
    param_ranges: Optional[Dict[str, Any]] = None,
    period: Optional[str] = None,
    fields: Optional[str] = None,
    metric: str = "sharpe",
    concurrency: int = 2,
) -> Dict[str, Any]:
    """创建回测批次: 1 个 batch_no (next_seq task_batch) + N 行 task.

    不执行, 由 api 层转发 strategy_exec; 完成后 strategy_exec 按 metric 回写 best_params。

    Returns:
        dict: batch_no / total_runs / mode / metric / sweep_keys / task_ids /
              strategy_id / script_id / stock_code / 日期 / period / fields / over_soft_limit
    Raises:
        StrategyError: NO_STRATEGY / NO_SCRIPT / MISSING_DATES / MISSING_PARAM /
                       MISSING_RANGES / UNKNOWN_PARAM / GRID_TOO_LARGE / INVALID_MODE
    """
    from server.services.script_strategy.scripts import get_script

    strat = _require_owned_strategy(strategy_id, user_id)
    if strat is None:
        raise StrategyError("NO_STRATEGY", f"strategy_id {strategy_id} 不存在或无权访问")
    sd = strat._data
    script = get_script(sd.get("script_id"), user_id, is_admin=False)
    if script is None:
        raise StrategyError("NO_SCRIPT", "策略所属脚本不存在或已删除")
    schema = script.get("params_schema") or []
    schema_by_key = {s.get("key"): s for s in schema}

    if not backtest_start_date or not backtest_end_date:
        raise StrategyError("MISSING_DATES", "回测必须指定 backtest_start_date / backtest_end_date")

    if mode == "single":
        if not params:
            raise StrategyError("MISSING_PARAM", "单次回测必须提供 params")
        validate_params_keys(params, schema_by_key)
        combos = [dict(params)]
        total_runs = 1
        sweep_keys: List[str] = []
    elif mode == "sweep":
        if not param_ranges:
            raise StrategyError("MISSING_RANGES", "参数扫描必须提供 param_ranges")
        expanded = expand_param_ranges(param_ranges, schema)
        combos = expanded["combos"]
        total_runs = expanded["total_runs"]
        sweep_keys = expanded["sweep_keys"]
    else:
        raise StrategyError("INVALID_MODE", f"mode 必须是 single|sweep, 收到 {mode!r}")

    batch_no = int(next_seq("task_batch"))
    task_ids = []
    for c in combos:
        t = create_task(
            user_id=user_id, strategy_id=strategy_id, stock_code=stock_code,
            params=c,
            description=sd.get("name", "") or f"strategy-{strategy_id}",
            backtest_start_date=backtest_start_date,
            backtest_end_date=backtest_end_date,
            period=period, fields=fields,
            mode="backtest", batch_no=batch_no, status="queued",
        )
        task_ids.append(t["id"])

    return {
        "batch_no": batch_no,
        "total_runs": total_runs,
        "mode": mode,
        "metric": metric,
        "concurrency": concurrency,
        "sweep_keys": sweep_keys,
        "strategy_id": strategy_id,
        "script_id": sd.get("script_id"),
        "stock_code": stock_code,
        "backtest_start_date": backtest_start_date,
        "backtest_end_date": backtest_end_date,
        "period": period,
        "fields": fields,
        "task_ids": task_ids,
        "over_soft_limit": total_runs > 64,
    }


def list_batches(
    strategy_id: int, user_id: int, is_admin: bool = False,
) -> Optional[List[Dict[str, Any]]]:
    """批次列表 (GROUP BY batch_no, 元信息从 task 派生).

    Returns:
        [{batch_no, created_at, mode, task_count, finished_count, failed_count,
          best_params, best_metric_value}] or None (无权限)
    """
    from server.tables import StrategyTask
    strat = _require_owned_strategy(strategy_id, user_id, is_admin=is_admin)
    if strat is None:
        return None

    rows = StrategyTask.query_by_fields({"strategy_id": strategy_id})
    groups: Dict[Any, List] = {}
    for r in rows:
        groups.setdefault(r._data.get("batch_no"), []).append(r)

    batches = []
    for bn, tasks in groups.items():
        finished = [t for t in tasks if t._data.get("status") == "finished"]
        best = None
        best_metric = None
        for t in finished:
            mv = _extract_metric_value(json_loads(t._data.get("backtest_result")))
            if mv is not None and (best_metric is None or mv > best_metric):
                best_metric = mv
                best = json_loads(t._data.get("params"))
        first = tasks[0]._data
        batches.append({
            "batch_no": bn,
            "created_at": iso(first.get("created_at")),
            "mode": first.get("mode"),
            "task_count": len(tasks),
            "finished_count": len(finished),
            "failed_count": sum(1 for t in tasks if t._data.get("status") == "failed"),
            "best_params": best,
            "best_metric_value": best_metric,
        })
    batches.sort(key=lambda b: -(b["batch_no"] or 0))
    return batches


def list_batch_tasks(
    strategy_id: int, batch_no: int, user_id: int, is_admin: bool = False,
) -> Optional[List[Dict[str, Any]]]:
    """批次内任务表格数据 (按 id 升序)"""
    from server.tables import StrategyTask
    strat = _require_owned_strategy(strategy_id, user_id, is_admin=is_admin)
    if strat is None:
        return None
    rows = StrategyTask.query_by_fields({"strategy_id": strategy_id, "batch_no": batch_no})
    rows.sort(key=lambda r: getattr(r, "_data", {}).get("id", 0))
    return [task_row_to_dict(r) for r in rows]


def create_live_batch(
    user_id: int, strategy_id: int, *, stock_code: str, fields: Optional[str] = None,
) -> Dict[str, Any]:
    """实盘启动: 校验 best_params 非空 + key ⊆ params_schema, 建 1 行 live task (新 batch_no).

    Raises:
        StrategyError: NO_STRATEGY / NO_BEST_PARAMS / NO_SCRIPT / PARAM_MISMATCH
    """
    from server.services.script_strategy.scripts import get_script

    strat = _require_owned_strategy(strategy_id, user_id)
    if strat is None:
        raise StrategyError("NO_STRATEGY", f"strategy_id {strategy_id} 不存在或无权访问")
    sd = strat._data
    best_params = json_loads(sd.get("best_params"))
    if not best_params:
        raise StrategyError("NO_BEST_PARAMS", "请先回测生成最优参数")
    script = get_script(sd.get("script_id"), user_id, is_admin=False)
    if script is None:
        raise StrategyError("NO_SCRIPT", "策略所属脚本不存在或已删除")
    schema_keys = {s.get("key") for s in (script.get("params_schema") or [])}
    missing = sorted(set(best_params.keys()) - schema_keys)
    if missing:
        raise StrategyError("PARAM_MISMATCH", f"best_params 含脚本 schema 之外字段: {missing}")

    batch_no = int(next_seq("task_batch"))
    t = create_task(
        user_id=user_id, strategy_id=strategy_id, stock_code=stock_code,
        params=best_params,
        description=sd.get("name", "") or f"strategy-{strategy_id}",
        fields=fields,
        mode="live", batch_no=batch_no, status="queued",
    )
    return {
        "batch_no": batch_no,
        "task_id": t["id"],
        "mode": "live",
        "strategy_id": strategy_id,
        "script_id": sd.get("script_id"),
        "stock_code": stock_code,
        "fields": fields,
        "params": best_params,
    }
