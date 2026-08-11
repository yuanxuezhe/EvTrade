"""
server/services/script_strategy/batches.py — 回测批次 + 聚合查询 (v123)

职责单一: 围绕 `strategy_task` 的批次操作。
- create_backtest_batch: 单次=1 行 task, 扫描=param_ranges 展开 N 行 task, 统一 task_batch 序号
- list_batches / list_batch_tasks: 虚拟 GROUP BY batch_no 聚合 (无批头表)

不执行运行时; 由 api 层转发 strategy_exec, 完成后 strategy_exec 回写 best_params。

v125: 策略模块纯回测, 实盘/黑盒跟随移除 (Part 2 另行设计)。
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from server.repo.orders import next_seq
from server.services.script_strategy._convert import (
    iso,
    json_loads,
    task_row_to_dict,
    TASK_LIST_COLUMNS,
)
from server.services.script_strategy.errors import StrategyError
from server.services.script_strategy.params import expand_param_ranges, validate_params_keys
from server.services.script_strategy.access import require_backtest_access
from server.services.script_strategy.tasks import create_task


def create_backtest_batch(
    user_id: int,
    strategy_id: int,
    *,
    mode: str,  # 'single' | 'sweep'
    stock_code: Optional[str] = None,
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

    v125 绑定标的: 策略有绑定 stock_code 时优先用它 (请求提供且不一致 → STOCK_MISMATCH);
    存量 NULL 行回退请求的 stock_code。

    Returns:
        dict: batch_no / total_runs / mode / metric / sweep_keys / task_ids /
              strategy_id / script_id / stock_code / 日期 / period / fields / over_soft_limit
    Raises:
        StrategyError: NO_STRATEGY / NO_SCRIPT / MISSING_DATES / MISSING_PARAM /
                       MISSING_RANGES / UNKNOWN_PARAM / GRID_TOO_LARGE / INVALID_MODE /
                       STOCK_MISMATCH / BACKTEST_FORBIDDEN
    """
    from server.services.script_strategy.scripts import get_script

    strat = require_backtest_access(strategy_id, user_id)
    sd = strat._data
    script = get_script(sd.get("script_id"), user_id, is_admin=False)
    if script is None:
        raise StrategyError("NO_SCRIPT", "策略所属脚本不存在或已删除")
    schema = script.get("params_schema") or []
    schema_by_key = {s.get("key"): s for s in schema}

    if not backtest_start_date or not backtest_end_date:
        raise StrategyError("MISSING_DATES", "回测必须指定 backtest_start_date / backtest_end_date")

    # v125 绑定标的: 策略有绑定 → 必须用它 (提供且不一致 → STOCK_MISMATCH);
    # 存量 NULL 行回退请求的 stock_code (旧行为)
    bound = sd.get("stock_code")
    if bound:
        if stock_code and stock_code != bound:
            raise StrategyError(
                "STOCK_MISMATCH", f"策略已绑定标的 {bound}, 与请求标的 {stock_code} 不一致")
        effective_stock = bound
    else:
        effective_stock = stock_code

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
            user_id=user_id, strategy_id=strategy_id, stock_code=effective_stock,
            params=c,
            description=sd.get("name", "") or f"strategy-{strategy_id}",
            backtest_start_date=backtest_start_date,
            backtest_end_date=backtest_end_date,
            period=period, fields=fields,
            mode="backtest", batch_no=batch_no, status="queued",
            metric=metric,  # 批次排序指标落库 (重测还原用)
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
        "stock_code": effective_stock,
        "backtest_start_date": backtest_start_date,
        "backtest_end_date": backtest_end_date,
        "period": period,
        "fields": fields,
        "task_ids": task_ids,
        "over_soft_limit": total_runs > 64,
    }


def list_batches(
    strategy_id: int, user_id: int, is_admin: bool = False,
) -> List[Dict[str, Any]]:
    """批次列表 (GROUP BY batch_no, 元信息从 task 派生).

    Returns:
        [{batch_no, created_at, mode, task_count, finished_count, failed_count,
          abandoned_count, abandoned, metric, best_params, best_metric_value}]
    Raises:
        StrategyError: BACKTEST_FORBIDDEN / NO_STRATEGY (非 owner/admin)

    v124 批次重测: 被重测替代的批次全部 task status='abandoned' → 不再计入
    finished/failed/best; 批次行标 abandoned=True + abandoned_count。
    """
    from server.tables import StrategyTask
    require_backtest_access(strategy_id, user_id, is_admin=is_admin)

    # 轻量列 (TASK_LIST_COLUMNS): 免拖回 backtest_result 大 blob,
    # 否则 SELECT * + ORDER BY 报 MySQL 1038 'Out of sort memory' (500)。
    rows = StrategyTask.query_by_fields(
        {"strategy_id": strategy_id}, columns=TASK_LIST_COLUMNS)
    groups: Dict[Any, List] = {}
    for r in rows:
        groups.setdefault(r._data.get("batch_no"), []).append(r)

    batches = []
    for bn, tasks in groups.items():
        # 重测废弃: abandoned task 不计入 finished/failed/best
        abandoned = [t for t in tasks if t._data.get("status") == "abandoned"]
        finished = [
            t for t in tasks
            if t._data.get("status") == "finished" and t._data.get("status") != "abandoned"
        ]
        best = None
        best_metric = None
        for t in finished:
            mv = t._data.get("backtest_metric_value")  # 已持久化, 不再解析 blob
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
            "abandoned_count": len(abandoned),
            "abandoned": len(abandoned) == len(tasks) > 0,
            "metric": first.get("metric") or "sharpe",  # 批次排序指标 (重测还原)
            "best_params": best,
            "best_metric_value": best_metric,
        })
    batches.sort(key=lambda b: -(b["batch_no"] or 0))
    return batches


def list_batch_tasks(
    strategy_id: int, batch_no: int, user_id: int, is_admin: bool = False,
) -> List[Dict[str, Any]]:
    """批次内任务表格数据 (按 id 升序).

    Raises:
        StrategyError: BACKTEST_FORBIDDEN / NO_STRATEGY (非 owner/admin)
    """
    from server.tables import StrategyTask
    require_backtest_access(strategy_id, user_id, is_admin=is_admin)
    rows = StrategyTask.query_by_fields(
        {"strategy_id": strategy_id, "batch_no": batch_no},
        columns=TASK_LIST_COLUMNS,
    )
    rows.sort(key=lambda r: getattr(r, "_data", {}).get("id", 0))
    return [task_row_to_dict(r) for r in rows]


def _reconstruct_ranges(combos: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """从批次 task params 重建 sweep param_ranges (供 strategy_exec forward 计数/校验).

    原批次由 create_backtest_batch 按 param_ranges 笛卡尔积生成 → 每字段不同取值集合
    唯一确定网格. 重建为 {key: {type: 'choice', values: [...]}} 与 strategy_exec 的
    iter_param_ranges 兼容, count_param_ranges 与原网格精确一致。
    """
    distinct: Dict[str, List[Any]] = {}
    for c in combos:
        for k, v in c.items():
            if k not in distinct:
                distinct[k] = []
            if v not in distinct[k]:
                distinct[k].append(v)
    return {k: {"type": "choice", "values": vals} for k, vals in distinct.items()}


def retest_batch(
    strategy_id: int, batch_no: int, user_id: int, is_admin: bool = False,
) -> Dict[str, Any]:
    """重测批次 (v124): 按原批次配置重建新批次, 原批次全部 task 置 'abandoned' 废弃.

    语义:
    - 新 batch_no = next_seq(task_batch); 新 task 沿用原 task 的 params/标的/区间/周期
    - 排序指标 metric 从原批次 task 读取 (v124 起落库, 老批次回填 'sharpe')
    - 原批次 task 全部 status → 'abandoned' (不再计入 finished/failed/best)
    - sweep 批次: param_ranges 由 task params 去重重建, 供 API 层转发 strategy_exec

    Raises:
        StrategyError: NO_STRATEGY / BATCH_NOT_FOUND / NOT_RETESTABLE (非回测批次) /
                       BATCH_RUNNING (批次仍有 queued/running task)
    """
    from server.tables import StrategyTask

    strat = require_backtest_access(strategy_id, user_id, is_admin=is_admin)
    sd = strat._data

    # 1. 读原批次 task (轻量列)
    rows = StrategyTask.query_by_fields(
        {"strategy_id": strategy_id, "batch_no": batch_no},
        columns=TASK_LIST_COLUMNS,
    )
    if not rows:
        raise StrategyError("BATCH_NOT_FOUND", f"batch_no {batch_no} 不存在")
    rows.sort(key=lambda r: getattr(r, "_data", {}).get("id", 0))

    first = rows[0]._data
    if first.get("mode") != "backtest":
        raise StrategyError("NOT_RETESTABLE", f"仅回测批次可重测, 当前 mode={first.get('mode')}")

    # 2. 运行中禁止重测 (strategy_exec 正在写这些 task 行, 废弃会被覆盖)
    active = [t for t in rows if t._data.get("status") in ("queued", "running")]
    if active:
        raise StrategyError(
            "BATCH_RUNNING",
            f"批次仍有 {len(active)} 个任务未结束 (queued/running), 请先等待完成或停止后再重测",
        )

    # 3. 重建批次 (新 batch_no, 沿用原配置)
    metric = first.get("metric") or "sharpe"
    combos = [json_loads(t._data.get("params"), default={}) for t in rows]
    is_sweep = len(combos) > 1
    new_batch_no = int(next_seq("task_batch"))
    task_ids = []
    for c in combos:
        t = create_task(
            user_id=user_id, strategy_id=strategy_id, stock_code=first.get("stock_code"),
            params=c,
            description=sd.get("name", "") or f"strategy-{strategy_id}",
            backtest_start_date=first.get("backtest_start_date"),
            backtest_end_date=first.get("backtest_end_date"),
            period=first.get("period"), fields=first.get("fields"),
            mode="backtest", batch_no=new_batch_no, status="queued",
            metric=metric,
        )
        task_ids.append(t["id"])

    # 4. 原批次全部 task → abandoned (废弃)
    StrategyTask.update_by_fields(
        {"status": "abandoned", "updated_at": datetime.now()},
        strategy_id=strategy_id, batch_no=batch_no,
    )

    return {
        "batch_no": new_batch_no,
        "total_runs": len(task_ids),
        "mode": "sweep" if is_sweep else "single",
        "metric": metric,
        "concurrency": 2,
        "strategy_id": strategy_id,
        "script_id": sd.get("script_id"),
        "stock_code": first.get("stock_code"),
        "backtest_start_date": first.get("backtest_start_date"),
        "backtest_end_date": first.get("backtest_end_date"),
        "period": first.get("period"),
        "fields": first.get("fields"),
        "task_ids": task_ids,
        "param_ranges": _reconstruct_ranges(combos) if is_sweep else None,
        "params": combos[0] if not is_sweep else None,
        "over_soft_limit": len(task_ids) > 64,
    }
