"""
server/services/script_strategy/strategies.py — 策略 CRUD + 回测批次 + 实盘门禁 (v123)

职责: 直接读写 `strategy` / `strategy_task` 表。
- 策略 CRUD (list / get / create / update / delete), 建策略不填参数、不定模式
- 回测批次: 单次=1 行 task, 扫描=按 param_ranges 类型驱动展开 N 行 task,
  统一分配 `task_batch` 序号 (batch_no), 不执行 (转发由 api 层负责)
- 批次聚合: GET batches / GET batch tasks (虚拟 GROUP BY batch_no, 无批头表)
- 实盘门禁: best_params 非空 + key ⊆ params_schema, 用 best_params 建 1 行 live task

运行时 (回测/实盘) 在 strategy_exec; 完成后由 strategy_exec 回写 best_params。
"""
import itertools
from datetime import datetime
from typing import Any, Dict, List, Optional

from server.services.script_strategy._convert import (
    json_dumps,
    json_loads,
    iso,
    script_row_to_dict,
    strategy_row_to_dict,
    task_row_to_dict,
    _extract_metric_value,
)
from server.services.script_strategy.tasks import create_task


class StrategyError(ValueError):
    """业务校验错误, 由 api 层映射为 400 {code, msg}"""

    def __init__(self, code: str, msg: str):
        super().__init__(msg)
        self.code = code
        self.msg = msg


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


def _strategy_public_derived(strat) -> bool:
    """策略派生自公开脚本 → 对其他用户可见"""
    from server.tables import StrategyScript
    d = getattr(strat, "_data", {})
    script = StrategyScript.query_one(user_id=d.get("user_id"), id=d.get("script_id"))
    if script is not None:
        return bool(getattr(script, "_data", {}).get("is_public"))
    return False


# ─────────────── Strategy CRUD ───────────────


def list_strategies(
    user_id: int, is_admin: bool = False,
    status: Optional[str] = None, only_mine: bool = False,
) -> List[Dict[str, Any]]:
    """列策略: 自己的 + 派生自公开脚本的 (admin 看全部)"""
    from server.tables import Strategy, StrategyScript
    if is_admin:
        rows = Strategy.query_all(order="desc")
    else:
        rows = Strategy.query_by_fields({"user_id": user_id})
        if not only_mine:
            public_script_ids = {
                r._data.get("id") for r in StrategyScript.query_by_fields({"is_public": 1})
            }
            for r in Strategy.query_all(order="desc"):
                d = r._data
                if d.get("user_id") == user_id:
                    continue  # 已在 rows
                if d.get("script_id") in public_script_ids:
                    rows.append(r)
        rows.sort(key=lambda r: getattr(r, "_data", {}).get("strategy_id", 0), reverse=True)
    out = []
    for r in rows:
        d = strategy_row_to_dict(r)
        if status and d.get("status") != status:
            continue
        out.append(d)
    return out


def get_strategy(strategy_id: int, user_id: int, is_admin: bool = False) -> Optional[Dict[str, Any]]:
    """策略详情 (含所属脚本信息)"""
    from server.tables import Strategy
    row = Strategy.query_one(strategy_id=strategy_id)
    if row is None:
        return None
    d = strategy_row_to_dict(row)
    if not is_admin and d.get("user_id") != user_id and not _strategy_public_derived(row):
        return None
    d["script"] = _resolve_script(d.get("user_id"), d.get("script_id"))
    return d


def create_strategy(user_id: int, name: str, script_id: str) -> Dict[str, Any]:
    """创建策略 (仅 {name, script_id}, 不填参数、不定模式)

    Raises:
        StrategyError: 脚本不存在/不可用
    """
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
    for task in StrategyTask.query_by_fields({"strategy_id": strategy_id}):
        StrategyTask.delete_one(id=task._data.get("id"))
    return Strategy.delete_one(strategy_id=strategy_id)


# ─────────────── param_ranges 展开 (v123 D5 类型驱动) ───────────────


def _expand_values(spec: Dict[str, Any]) -> List[Any]:
    """单参取值序列:
    - int/float: start..end 步进 step, 含端点 (未对齐 step 的 end 不包含)
    - choice: 值列表每个值一组
    - string: 固定值, 不参与扫描
    """
    t = spec.get("type")
    if t in ("int", "float"):
        start = float(spec["start"])
        end = float(spec["end"])
        step = float(spec.get("step") or 1)
        vals = []
        v = start
        while v <= end:
            vals.append(int(round(v)) if t == "int" else round(v, 10))
            v += step
        return vals
    if t == "choice":
        return list(spec.get("values") or [])
    if t == "string":
        return [spec.get("value", spec.get("default", ""))]
    raise StrategyError("INVALID_PARAM_RANGE", f"不支持的参数类型: {t!r}")


def expand_param_ranges(
    param_ranges: Dict[str, Dict[str, Any]], schema: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """展开参数扫描: 参与字段笛卡尔积 + 未参与字段取 schema default 固定值.

    Returns:
        {"combos": [...], "total_runs": int, "sweep_keys": [...], "over_soft_limit": bool}
    Raises:
        StrategyError: GRID_TOO_LARGE (>512) / UNKNOWN_PARAM
    """
    schema_by_key = {s.get("key"): s for s in schema}
    for key in param_ranges:
        if key not in schema_by_key:
            raise StrategyError("UNKNOWN_PARAM", f"字段 {key!r} 不在脚本 params_schema 中")

    values_per_key: Dict[str, List[Any]] = {}
    for key, spec in param_ranges.items():
        spec = dict(spec)
        spec.setdefault("type", schema_by_key[key].get("type", "int"))
        values_per_key[key] = _expand_values(spec)

    sweep_keys = list(values_per_key.keys())
    if sweep_keys:
        combos = [
            dict(zip(sweep_keys, combo))
            for combo in itertools.product(*[values_per_key[k] for k in sweep_keys])
        ]
    else:
        combos = [{}]
    total_runs = len(combos)
    if total_runs > 512:
        raise StrategyError("GRID_TOO_LARGE", f"组合数 {total_runs} 超过硬上限 512")

    fixed = {s.get("key"): s.get("default") for s in schema if s.get("key") not in values_per_key}
    full_combos = [{**fixed, **c} for c in combos]
    return {
        "combos": full_combos,
        "total_runs": total_runs,
        "sweep_keys": sweep_keys,
        "over_soft_limit": total_runs > 64,
    }


# ─────────────── 回测批次 ───────────────


def _validate_params_keys(params: Dict[str, Any], schema_by_key: Dict[str, Any]) -> None:
    for key in params:
        if key not in schema_by_key:
            raise StrategyError("UNKNOWN_PARAM", f"字段 {key!r} 不在脚本 params_schema 中")


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
    from server.tables import Strategy
    from server.repo.orders import next_seq
    from server.services.script_strategy.scripts import get_script

    strat = Strategy.query_one(strategy_id=strategy_id)
    if strat is None or getattr(strat, "_data", {}).get("user_id") != user_id:
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
        _validate_params_keys(params, schema_by_key)
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
    from server.tables import Strategy, StrategyTask
    strat = Strategy.query_one(strategy_id=strategy_id)
    if strat is None:
        return None
    if not is_admin and getattr(strat, "_data", {}).get("user_id") != user_id \
            and not _strategy_public_derived(strat):
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
    from server.tables import Strategy, StrategyTask
    strat = Strategy.query_one(strategy_id=strategy_id)
    if strat is None:
        return None
    if not is_admin and getattr(strat, "_data", {}).get("user_id") != user_id \
            and not _strategy_public_derived(strat):
        return None
    rows = StrategyTask.query_by_fields({"strategy_id": strategy_id, "batch_no": batch_no})
    rows.sort(key=lambda r: getattr(r, "_data", {}).get("id", 0))
    return [task_row_to_dict(r) for r in rows]


# ─────────────── 实盘门禁 (v123 REQ-STRAT-015 / REQ-SE-009) ───────────────


def create_live_batch(
    user_id: int, strategy_id: int, *, stock_code: str, fields: Optional[str] = None,
) -> Dict[str, Any]:
    """实盘启动: 校验 best_params 非空 + key ⊆ params_schema, 建 1 行 live task (新 batch_no).

    Raises:
        StrategyError: NO_STRATEGY / NO_BEST_PARAMS / NO_SCRIPT / PARAM_MISMATCH
    """
    from server.tables import Strategy
    from server.repo.orders import next_seq
    from server.services.script_strategy.scripts import get_script

    strat = Strategy.query_one(strategy_id=strategy_id)
    if strat is None or getattr(strat, "_data", {}).get("user_id") != user_id:
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
