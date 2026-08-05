"""
server/strategy/service.py — script + task 业务服务层

📌 职责:
- Script CRUD: list / get / create / update / delete (走 StrategyScript TableBase)
- Task 创建 + 启动:
    - mode='backtest' → 后台线程跑 run_grid_backtest → 写 strategy_task.backtest_result + best_params
    - mode='live'     → 启动 LiveRunner (asyncio task) → status='running'
- Task 控制: stop / delete / get_result / get_logs
"""
from __future__ import annotations

import asyncio as _asyncio
import json
import logging
import time
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from server.strategy.runtime import (
    run_grid_backtest, start_live_runner, stop_live_runner,
    is_running as is_live_running,
    SandboxError,
)

log = logging.getLogger(__name__)


# ─────────────── Script CRUD ───────────────


def _json_dumps(v: Any) -> Any:
    return json.dumps(v, ensure_ascii=False) if v is not None else None


def _json_loads(v: Any, default=None):
    if v is None or v == "":
        return default
    if isinstance(v, (list, dict)):
        return v
    try:
        return json.loads(v)
    except (ValueError, TypeError):
        return default


# ─────────────── Script ───────────────


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
        # 用户看自己的 + is_public=1 的公开脚本 (跨用户)
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
        d = _script_row_to_dict(r)
        if name and name.lower() not in d.get("name", "").lower():
            continue
        if status and d.get("status") != status:
            continue
        out.append(d)
    return out


def get_script(script_id: str, user_id: int, is_admin: bool = False) -> Optional[Dict[str, Any]]:
    """按 (user_id, id) 取脚本 (v90+ 复合 PK)

    用户优先查自己的, 否则查公开的
    """
    from server.tables import StrategyScript
    row = StrategyScript.query_one(user_id=user_id, id=script_id)
    if row is not None:
        return _script_row_to_dict(row)
    if is_admin:
        candidates = StrategyScript.query_by_fields({"id": script_id})
    else:
        candidates = StrategyScript.query_by_fields({"id": script_id, "is_public": 1})
    if candidates:
        return _script_row_to_dict(candidates[0])
    return None


def get_script_by_name(name: str, user_id: int, is_admin: bool = False) -> Optional[Dict[str, Any]]:
    """按 name 查脚本 (admin 跨用户, 用户仅自己的)

    优先取 active 中 name 完全匹配的 (多个 active 取最新)
    """
    from server.tables import StrategyScript
    if is_admin:
        rows = StrategyScript.query_by_fields({"name": name})
    else:
        rows = StrategyScript.query_by_fields({"user_id": user_id, "name": name})
    if not rows:
        return None
    # 排序: active 优先, 然后 id desc
    rows.sort(key=lambda r: (
        0 if getattr(r, "_data", {}).get("status") == "active" else 1,
        -getattr(r, "_data", {}).get("id", 0),
    ))
    return _script_row_to_dict(rows[0])


def create_script(
    user_id: int, name: str, code: str, params_schema: List[Dict[str, Any]],
    description: str = "",
    is_public: bool = False,
) -> Dict[str, Any]:
    """创建脚本 (v90+ 改复合 PK)

    id 默认 = name (用户自命名, 同用户内唯一, PK = (user_id, id))
    is_public: True → 其他用户可见
    """
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
        "params_schema": _json_dumps(params_schema),
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
    return _script_row_to_dict(row)


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
        update_data["params_schema"] = _json_dumps(patch["params_schema"])
    if update_data:
        update_data["updated_at"] = datetime.now()
        StrategyScript.upsert_one(update_data, user_id=actual_user_id, id=script_id)
    return get_script(script_id, actual_user_id, is_admin)


def delete_script(script_id: str, user_id: int, is_admin: bool) -> bool:
    """删除脚本 (v90+ 复合 PK)

    级联: 先删 strategy_task 中所有引用此 (user_id, script_id) 的 task, 再删 script。
    v90+ FK 是严格约束 (FK fk_task_script), 必须先删子表。
    """
    from server.tables import StrategyScript, StrategyTask
    row = StrategyScript.query_one(user_id=user_id, id=script_id)
    if row is None:
        return False
    if not is_admin and getattr(row, "_data", {}).get("user_id") != user_id:
        return False
    # 级联删 task (FK 严格约束, 不能直接删 script)
    related_tasks = StrategyTask.query_by_fields({"user_id": user_id, "script_id": script_id})
    for task in related_tasks:
        task_id = task._data.get("id")
        if is_live_running(task_id):
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(_async_stop_live(task_id))
            except RuntimeError:
                pass
        StrategyTask.delete_one(id=task_id)
    return StrategyScript.delete_one(user_id=user_id, id=script_id)


def _script_row_to_dict(row) -> Dict[str, Any]:
    return {
        "id": getattr(row, "_data", {}).get("id"),  # v90+ str (用户自命名)
        "user_id": getattr(row, "_data", {}).get("user_id"),
        "name": getattr(row, "_data", {}).get("name", ""),
        "code": getattr(row, "_data", {}).get("code", ""),
        "params_schema": _json_loads(getattr(row, "_data", {}).get("params_schema"), default=[]),
        "description": getattr(row, "_data", {}).get("description", ""),
        "status": getattr(row, "_data", {}).get("status", "active"),
        "is_public": bool(getattr(row, "_data", {}).get("is_public", 0)),  # v90+
        "created_at": _iso(getattr(row, "_data", {}).get("created_at")),
        "updated_at": _iso(getattr(row, "_data", {}).get("updated_at")),
    }


def _task_row_to_dict(row) -> Dict[str, Any]:
    return {
        "id": getattr(row, "_data", {}).get("id"),
        "user_id": getattr(row, "_data", {}).get("user_id"),
        "script_id": getattr(row, "_data", {}).get("script_id"),
        "stock_code": getattr(row, "_data", {}).get("stock_code", ""),
        "mode": getattr(row, "_data", {}).get("mode"),
        "status": getattr(row, "_data", {}).get("status", ""),
        "params": _json_loads(getattr(row, "_data", {}).get("params"), default={}),
        "backtest_result": _json_loads(getattr(row, "_data", {}).get("backtest_result")),
        "best_params": _json_loads(getattr(row, "_data", {}).get("best_params")),
        "backtest_start_date": getattr(row, "_data", {}).get("backtest_start_date"),
        "backtest_end_date": getattr(row, "_data", {}).get("backtest_end_date"),
        "period": getattr(row, "_data", {}).get("period"),
        "fields": getattr(row, "_data", {}).get("fields"),
        "pnl": getattr(row, "_data", {}).get("pnl", 0.0) or 0.0,
        "positions": _json_loads(getattr(row, "_data", {}).get("positions"), default={}),
        "trades_count": getattr(row, "_data", {}).get("trades_count", 0) or 0,
        "live_signals": _json_loads(getattr(row, "_data", {}).get("live_signals"), default=[]),
        "progress": _json_loads(getattr(row, "_data", {}).get("progress"), default=None),
        "started_at": _iso(getattr(row, "_data", {}).get("started_at")),
        "finished_at": _iso(getattr(row, "_data", {}).get("finished_at")),
        "error_msg": getattr(row, "_data", {}).get("error_msg"),
        "created_at": _iso(getattr(row, "_data", {}).get("created_at")),
        "updated_at": _iso(getattr(row, "_data", {}).get("updated_at")),
    }


# ─────────────── Task ───────────────


def list_tasks(
    user_id: int, is_admin: bool = False, status: Optional[str] = None,
    mode: Optional[str] = None,
) -> List[Dict[str, Any]]:
    from server.tables import StrategyTask
    filters = {}
    if not is_admin:
        filters["user_id"] = user_id
    if status:
        filters["status"] = status
    if mode:
        filters["mode"] = mode
    if filters:
        rows = StrategyTask.query_by_fields(filters)
    else:
        rows = StrategyTask.query_all(order="desc")
        rows.sort(key=lambda r: getattr(r, "_data", {}).get("id", 0), reverse=True)
    return [_task_row_to_dict(r) for r in rows]


def get_task(task_id: int, user_id: int, is_admin: bool = False) -> Optional[Dict[str, Any]]:
    from server.tables import StrategyTask
    row = StrategyTask.query_one(id=task_id)
    if row is None:
        return None
    if not is_admin and getattr(row, "_data", {}).get("user_id") != user_id:
        return None
    return _task_row_to_dict(row)


def create_task(
    user_id: int,
    script_id: int,
    stock_code: str,
    params: Dict[str, Any],
    *,
    backtest_start_date: Optional[str] = None,
    backtest_end_date: Optional[str] = None,
    period: Optional[str] = None,
    fields: Optional[str] = None,
) -> Dict[str, Any]:
    """创建任务 (不立即执行, status='created'), 需再调 /tasks/{id}/run 触发

    不指定 mode: 任务入库后 status='created' (或 'pending'), 等用户调 run_task 触发
    回测所需的 start/end/period 在 run 时再传 (create 时允许先存默认值, 后续可被 run 覆盖)

    Raises:
        ValueError: 脚本不存在 / 权限
    """
    from server.tables import StrategyTask, StrategyScript

    script = StrategyScript.query_one(user_id=user_id, id=script_id)
    if script is None:
        raise ValueError(f"script_id {script_id} 不存在 (user_id={user_id})")

    now = datetime.now()
    data = {
        "user_id": user_id,
        "script_id": script_id,
        "stock_code": stock_code,
        # mode 字段保留在表里但创建时不填; run 时再写
        "mode": None,
        "status": "created",     # 仅创建, 未运行
        "params": _json_dumps(params),
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


def run_task(
    task_id: int,
    user_id: int,
    is_admin: bool,
    mode: str,
    *,
    backtest_start_date: Optional[str] = None,
    backtest_end_date: Optional[str] = None,
    period: Optional[str] = None,
    fields: Optional[str] = None,
) -> Dict[str, Any]:
    """触发任务执行 (回测 / 实盘)

    📌 必须先 create_task 调过, 才能 run_task
    📌 mode: 'backtest' / 'live'
    📌 回测参数 (start/end/period) 在此覆盖 task 已有值

    Raises:
        ValueError: mode 未知 / 脚本不存在 / 权限
        RuntimeError: 状态不允许 (已经在 running/live)
    """
    from server.tables import StrategyTask, StrategyScript

    if mode not in ("backtest", "live"):
        raise ValueError(f"未知 mode: {mode!r}")

    row = StrategyTask.query_one(id=task_id)
    if row is None:
        raise ValueError(f"task_id {task_id} 不存在")
    if not is_admin and getattr(row, "_data", {}).get("user_id") != user_id:
        raise ValueError("无权操作该任务")

    cur_status = getattr(row, "_data", {}).get("status")
    if cur_status in ("running", "live"):
        raise RuntimeError(f"任务已在运行 (status={cur_status}), 请先停止")

    # 读最新值
    task_data = row._data
    stock_code = task_data.get("stock_code")
    params = _json_loads(task_data.get("params"), default={})
    task_user_id = task_data.get("user_id")
    script_id = task_data.get("script_id")

    script = StrategyScript.query_one(user_id=task_user_id, id=script_id)
    if script is None:
        raise ValueError(f"task 关联的 script {script_id} 不存在 (user_id={task_user_id})")
    code = getattr(script, "_data", {}).get("code")

    # 覆盖参数 (回测时优先用 run 时传的)
    # 用 Row.update() 而非 upsert_one: 后者对缺失字段填 0/'' 默认值, 触发 FK 失败
    if backtest_start_date or backtest_end_date or period or fields:
        row = StrategyTask.query_one(id=task_id)
        if row is None:
            raise ValueError(f"task_id {task_id} 不存在")
        if backtest_start_date:
            row["backtest_start_date"] = backtest_start_date
        if backtest_end_date:
            row["backtest_end_date"] = backtest_end_date
        if period:
            row["period"] = period
        if fields:
            row["fields"] = fields
        row["updated_at"] = datetime.now()
        row.update()

    # 重读最新 (after patches)
    row = StrategyTask.query_one(id=task_id)
    period_v = getattr(row, "_data", {}).get("period") or "1d"
    start_v = getattr(row, "_data", {}).get("backtest_start_date")
    end_v = getattr(row, "_data", {}).get("backtest_end_date")
    fields_v = getattr(row, "_data", {}).get("fields")  # 可空, fetch_his_bars 用 DEFAULT_FIELDS

    # 写 mode + running + started_at (同样用 update 避免 INSERT 分支)
    row = StrategyTask.query_one(id=task_id)
    row["mode"] = mode
    row["status"] = "running"
    row["started_at"] = datetime.now()
    row["updated_at"] = datetime.now()
    row["finished_at"] = None
    row["error_msg"] = None
    row.update()

    if mode == "backtest":
        # 后台线程跑 (回测是 sync 计算)
        t = threading.Thread(
            target=_run_backtest_thread,
            args=(task_id, code, params, stock_code, period_v, start_v, end_v, fields_v),
            daemon=True,
            name=f"backtest-{task_id}",
        )
        t.start()
    else:  # live
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # 同步环境 (测试 / evctl): 改用 ensure_future to main loop (后台)
            asyncio.ensure_future(_async_start_live(task_id, code, params, stock_code))
        else:
            loop.create_task(_async_start_live(task_id, code, params, stock_code))

    return get_task(task_id, user_id, is_admin=True)


async def _async_start_live(task_id: int, code: str, params: Dict, stock_code: str) -> None:
    try:
        await start_live_runner(task_id, code, params, stock_code)
        # live 模式下状态保持 'running' (持续运行) 或改 'live'
        _set_task_status(task_id, "running")
    except Exception as e:
        log.exception("live task %d start failed", task_id)
        _set_task_status(task_id, "failed", error=str(e))


def stop_task(task_id: int, user_id: int, is_admin: bool = False) -> bool:
    """停止任务 (live 立即停; backtest 仅标记 stopped)"""
    from server.tables import StrategyTask
    row = StrategyTask.query_one(id=task_id)
    if row is None:
        return False
    if not is_admin and getattr(row, "_data", {}).get("user_id") != user_id:
        return False
    mode = getattr(row, "_data", {}).get("mode")
    if mode == "live":
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_async_stop_live(task_id))
        except RuntimeError:
            pass
        return True
    else:
        _set_task_status(task_id, "stopped")
        return True


async def _async_stop_live(task_id: int) -> None:
    await stop_live_runner(task_id)
    _set_task_status(task_id, "stopped")


def delete_task(task_id: int, user_id: int, is_admin: bool = False) -> bool:
    from server.tables import StrategyTask
    row = StrategyTask.query_one(id=task_id)
    if row is None:
        return False
    if not is_admin and getattr(row, "_data", {}).get("user_id") != user_id:
        return False
    if is_live_running(task_id):
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_async_stop_live(task_id))
        except RuntimeError:
            pass
    return StrategyTask.delete_one(id=task_id)


def get_task_logs(task_id: int, user_id: int, is_admin: bool = False) -> Optional[Dict[str, Any]]:
    """返 task 详情 + (回测模式) audit_log + (实盘模式) 当前状态"""
    t = get_task(task_id, user_id, is_admin)
    if t is None:
        return None
    if t.get("mode") == "backtest":
        logs = (t.get("backtest_result") or {}).get("trades", []) if t.get("backtest_result") else []
    else:
        logs = []
    return {**t, "logs": logs}


def get_task_signals(
    task_id: int, user_id: int, is_admin: bool = False,
    type_filter: Optional[str] = None, limit: int = 500,
) -> Optional[Dict[str, Any]]:
    """返 task 信号流 + 进度时间轴 (用于详情面板)

    Args:
        type_filter: 过滤 type ('BUY' / 'SELL' / 'INFO' / 'WARN'), None=全部
        limit: 最多返回条数 (从尾部截取)

    Returns:
        dict {mode, signals, progress, total_signals} or None
    """
    from server.tables import StrategyTask
    row = StrategyTask.query_one(id=task_id)
    if row is None:
        return None
    if not is_admin and getattr(row, "_data", {}).get("user_id") != user_id:
        return None

    mode = getattr(row, "_data", {}).get("mode")

    if mode == "backtest":
        # 回测信号 + 进度都在 backtest_result.best 里
        result = _json_loads(getattr(row, "_data", {}).get("backtest_result"))
        signals = (result or {}).get("best", {}).get("signal_log", []) if result else []
        progress = (result or {}).get("best", {}).get("progress_log", []) if result else []
    elif mode == "live":
        # 实盘信号在 live_signals
        signals = _json_loads(getattr(row, "_data", {}).get("live_signals"), default=[])
        # 实盘暂不存 progress (进度可前端用 current_price / 当前持仓 推算)
        progress = []
    else:
        signals = []
        progress = []

    # 过滤 type
    if type_filter:
        signals = [s for s in signals if s.get("type") == type_filter]

    total_signals = len(signals)
    # 尾部截 limit 条
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

    Args:
        trigger_type: 过滤 (BUY/SELL/INFO/...), None=全部
        trd_date: 过滤交易日 (YYYYMMDD), None=全部
        limit: 最多返多少条

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
    # 按 id 升序 (时间正序)
    rows.sort(key=lambda r: getattr(r, "_data", {}).get("id", 0))

    audit_list = []
    for r in rows:
        d = getattr(r, "_data", {})
        audit_list.append({
            "id": d.get("id"),
            "task_id": d.get("task_id"),
            "stime": d.get("stime"),
            "trd_date": d.get("trd_date"),
            "phase": d.get("phase"),
            "trigger_type": d.get("trigger_type"),
            "stock_code": d.get("stock_code"),
            "price": d.get("price"),
            "volume": d.get("volume"),
            "indicators": _json_loads(d.get("indicators"), default={}),
            "state": _json_loads(d.get("state"), default={}),
            "msg": d.get("msg"),
            "order_no": d.get("order_no"),
            "payload": _json_loads(d.get("payload"), default={}),
            "created_at": _iso(d.get("created_at")),
        })

    total = len(audit_list)
    if limit > 0:
        truncated = total > limit
        # 默认返尾部最新 limit 条
        audit_list = audit_list[-limit:]
    else:
        truncated = False

    return {
        "audit": audit_list,
        "total": total,
        "truncated": truncated,
    }


# ─────────────── 内部 helper ───────────────


def _set_task_status(task_id: int, status: str, *, error: Optional[str] = None) -> None:
    """更新 task status / error_msg / finished_at (纯 UPDATE, 不触发 FK 风险)

    v91.4: 同时 ws broadcast (前端 status 实时刷新)
    """
    from server.tables import StrategyTask
    row = StrategyTask.query_one(id=task_id)
    if row is None:
        return
    row["status"] = status
    row["updated_at"] = datetime.now()
    if status in ("done", "failed", "stopped"):
        row["finished_at"] = datetime.now()
    if error is not None:
        row["error_msg"] = error[:500]
    row.update()
    # v91.4: ws 推送 (兼容 sync 线程 — 用 main loop)
    try:
        from server.ws.manager import ws_manager as _ws_manager
        import asyncio as _asyncio
        payload = {
            "task_id": task_id,
            "status": status,
            "progress": {"phase": status, "msg": error or f"task {status}"},
        }
        main_loop = getattr(_ws_manager, '_main_loop', None)
        if main_loop is not None and main_loop.is_running():
            _asyncio.run_coroutine_threadsafe(
                _ws_manager.broadcast("task_progress_update", payload),
                main_loop
            )
        else:
            try:
                loop = _asyncio.get_running_loop()
                loop.create_task(_ws_manager.broadcast("task_progress_update", payload))
            except RuntimeError:
                log.debug("ws broadcast skip: no main loop registered")
    except Exception as ws_e:
        log.warning("ws broadcast failed: %s", ws_e)


def _run_backtest_thread(
    task_id: int, code: str, params: Dict, stock_code: str, period: str,
    start_date: Optional[str], end_date: Optional[str], fields: Optional[str] = None,
) -> None:
    """回测主线程: 拉历史 bar + grid backtest + 写结果

    每个阶段都打 log, 失败时 execution_log 也保留
    """
    from server.strategy.runtime.grid import expand_params
    from server.strategy.runtime.backtest import run_grid_backtest, BacktestEngine
    from server.strategy.runtime.his_hq import fetch_his_bars
    from server.tables import StrategyScript, StrategyTask

    # status 已在外层 set 为 running (run_task 调用前)
    try:
        # === 阶段 0: 启动 ===
        _set_task_progress(task_id, {
            "phase": "start", "current": 0, "total": 4,
            "elapsed_ms": 0, "msg": "回测启动",
        })
        log.info("[task=%d] === STAGE 0: 进入后台线程, 准备开始 ===", task_id)

        # === 阶段 1: 拉历史 bars ===
        if not start_date or not end_date:
            log.error("[task=%d] backtest failed: 缺少起止日期", task_id)
            _set_task_status(task_id, "failed", error="缺少回测起止日期")
            return
        log.info("[task=%d] === STAGE 1: fetch history bars === stock=%s %s~%s period=%s fields=%s",
                 task_id, stock_code, start_date, end_date, period, fields or 'default')
        _set_task_progress(task_id, {
            "phase": "fetch_his_bars_sending", "current": 1, "total": 4,
            "msg": f"📡 发 broker 请求: {stock_code} {start_date}~{end_date} period={period} fields={fields or 'open,close,high,low'}",
        })
        t1 = time.time()
        # 阶段 1a: 拉 broker reply
        _set_task_progress(task_id, {
            "phase": "fetch_his_bars_waiting", "current": 1, "total": 4,
            "msg": "⏳ 等待 broker reply (30s timeout)",
        })
        bars = fetch_his_bars(stock_code, start_date, end_date, period=period, fields=fields or "open,close,high,low")
        elapsed = time.time() - t1
        log.info("[task=%d] fetch_his_bars done: %d bars, %.2fs",
                 task_id, len(bars), elapsed)
        # 阶段 1b: 收到, 解析
        if bars:
            _set_task_progress(task_id, {
                "phase": "fetch_his_bars_done", "current": 1, "total": 4,
                "msg": f"✅ 拉取成功: {len(bars)} bars ({elapsed:.1f}s), "
                       f"首 {bars[0].get('stime', '?')} 末 {bars[-1].get('stime', '?')}",
                "bar_count": len(bars),
                "fetch_elapsed": elapsed,
            })
        else:
            _set_task_progress(task_id, {
                "phase": "fetch_his_bars_empty", "current": 1, "total": 4,
                "msg": f"❌ broker 未返回数据 ({elapsed:.1f}s)",
                "fetch_elapsed": elapsed,
            })
        if not bars:
            log.error("[task=%d] backtest failed: broker his_hq 未返回数据 (URL=%s queue=%s)",
                      task_id,
                      __import__("server.strategy.runtime.his_hq", fromlist=["_get_config"])._get_config()["req_queue"],
                      stock_code)
            _set_task_status(task_id, "failed",
                             error=f"未拉到历史数据 (stock={stock_code} {start_date}~{end_date} period={period}); broker his_hq 可能未响应")
            return

        # === 阶段 2: expand params + backtest ===
        log.info("[task=%d] === STAGE 2: expand params + backtest ===", task_id)
        _set_task_progress(task_id, {
            "phase": "expand_params", "current": 2, "total": 4,
            "msg": "展开参数组合",
        })
        pk = _get_task_script_pk(task_id)
        script = StrategyScript.query_one(user_id=pk[0], id=pk[1]) if pk else None
        params_schema = _json_loads(getattr(script, "_data", {}).get("params_schema") if script else "[]", default=[])

        try:
            expanded = expand_params(params_schema) if params_schema else [params or {}]
            log.info("[task=%d] params_schema → %d combinations: %s",
                     task_id, len(expanded), expanded)
        except ValueError as e:
            log.error("[task=%d] 参数展开失败: %s", task_id, e)
            _set_task_status(task_id, "failed", error=f"参数展开失败: {e}")
            return

        t2 = time.time()
        best_result_dict = None
        all_results = []
        best = None

        # 进度回调
        def _on_progress_bar(current, total_bars):
            _set_task_progress(task_id, {
                "phase": "backtest_bar", "current": 3, "total": 4,
                "bar_idx": current, "total_bars": total_bars,
                "pct": round(current / total_bars * 100, 1) if total_bars > 0 else 0,
                "msg": f"bar {current}/{total_bars} ({current*100//total_bars}%)",
            })

        def _on_progress_combo(current, total_combos, result, params):
            """grid combo 进度 (每 5% 一次, 避免 DB 写入爆炸)"""
            r = result.to_dict() if hasattr(result, "to_dict") else (result or {})
            # 每 5% 或首/末次才写 DB
            if current % max(1, total_combos // 20) == 0 or current == total_combos or current == 1:
                _set_task_progress(task_id, {
                    "phase": "grid_combo", "current": 3, "total": 4,
                    "combo_idx": current, "total_combos": total_combos,
                    "pct": round(current / total_combos * 100, 1) if total_combos > 0 else 0,
                    "msg": f"combo {current}/{total_combos} pnl={r.get('pnl', 0):.2f}",
                    "running_combo_params": params,
                })

        if len(expanded) == 1:
            log.info("[task=%d] single combo: %s", task_id, expanded[0])
            engine = BacktestEngine(
                code, expanded[0], bars, stock_code, period=period,
                task_id=task_id, verbose=True,
                on_progress=_on_progress_bar,
            )
            result = engine.run()
            best_result_dict = result.to_dict()
            best = {"params": expanded[0], "result": best_result_dict}
            all_results = [best]
        else:
            log.info("[task=%d] grid mode: %d combos", task_id, len(expanded))
            combined = run_grid_backtest(
                code, params_schema, bars, stock_code,
                period=period, task_id=task_id, verbose=False,
                on_progress=_on_progress_combo,
            )
            best = {"params": combined["best_params"], "result": combined["best_result"]}
            all_results = combined["all_results"]
            best_result_dict = combined["best_result"]

        log.info("[task=%d] backtest 计算耗时: %.2fs", task_id, time.time() - t2)

        # === 阶段 3: 写结果 ===
        log.info("[task=%d] === STAGE 3: write result ===", task_id)
        _set_task_progress(task_id, {
            "phase": "write_result", "current": 3, "total": 4,
            "msg": "写结果到数据库",
        })
        from server.tables import StrategyTask
        row = StrategyTask.query_one(id=task_id)
        if row is not None:
            all_summary = []
            for r in all_results:
                all_summary.append({
                    "params": r["params"],
                    "pnl": r["result"].get("pnl", 0.0),
                    "pnl_pct": r["result"].get("pnl_pct", 0.0),
                    "trades_count": r["result"].get("trades_count", 0),
                })
            # execution_log 从 best_result 抽出 (grid 模式下只有 best 有完整 log)
            execution_log = (best_result_dict or {}).get("execution_log", [])
            row["status"] = "done"
            row["backtest_result"] = _json_dumps({
                "best": best["result"],
                "all_summary": all_summary,
                "combinations": len(all_results),
                "execution_log": execution_log,  # 🆕 全阶段时间轴 (前端面板用)
                "total_bars": len(bars),
                "elapsed_seconds": round(time.time() - t1, 3),
            })
            row["best_params"] = _json_dumps(best["params"])
            row["pnl"] = best["result"].get("pnl", 0.0)
            row["trades_count"] = best["result"].get("trades_count", 0)
            row["finished_at"] = datetime.now()
            row["updated_at"] = datetime.now()
            row.update()
        # === 阶段 4: done ===
        _set_task_progress(task_id, {
            "phase": "done", "current": 4, "total": 4,
            "msg": f"完成 pnl={best['result'].get('pnl', 0):.2f} trades={best['result'].get('trades_count', 0)}",
            "elapsed_ms": int((time.time() - t1) * 1000),
        })
        log.info("[task=%d] === DONE === pnl=%.2f best_params=%s trades=%d",
                 task_id, best["result"].get("pnl", 0), best["params"], best["result"].get("trades_count", 0))
    except Exception as e:
        log.exception("[task=%d] backtest 顶层异常", task_id)
        _set_task_status(task_id, "failed", error=str(e))
        _set_task_progress(task_id, {
            "phase": "failed", "current": 0, "total": 4,
            "msg": f"异常: {e}",
        })


def _set_task_progress(task_id: int, progress: Dict[str, Any]) -> None:
    """写 progress 到 strategy_task.progress (轻量更新)

    失败也不抛 (进度是 best-effort)
    v91.4: 同时 ws broadcast 到 task_progress_update channel
    """
    from server.tables import StrategyTask
    try:
        row = StrategyTask.query_one(id=task_id)
        if row is None:
            return
        progress["updated_at"] = datetime.now().isoformat(timespec="seconds")
        row["progress"] = _json_dumps(progress)
        row.update()
        # v91.4: ws 推送 (前端实时更新, 不轮询)
        try:
            from server.ws.manager import ws_manager as _ws_manager
            import asyncio
            payload = {
                "task_id": task_id,
                "status": row._data.get("status"),
                "progress": dict(progress),
            }
            main_loop = getattr(_ws_manager, '_main_loop', None)
            if main_loop is not None and main_loop.is_running():
                _asyncio.run_coroutine_threadsafe(
                    _ws_manager.broadcast("task_progress_update", payload),
                    main_loop
                )
            else:
                try:
                    loop = _asyncio.get_running_loop()
                    loop.create_task(_ws_manager.broadcast("task_progress_update", payload))
                except RuntimeError:
                    log.debug("ws broadcast skip: no main loop registered")
        except Exception as ws_e:
            log.warning("ws broadcast failed: %s", ws_e)
    except Exception as e:
        log.warning("_set_task_progress(%d) 失败 (忽略): %s", task_id, e)


def sweep_stale_running_tasks(max_idle_seconds: int = 300) -> int:
    """清理卡死的 running task (启动时调用)

    适用场景: 后端重启 / broker 死 / 任务线程死了但 status 仍 running
    判定: status='running' AND progress.updated_at > max_idle_seconds 没动 → 标 failed

    Returns:
        被清理的任务数
    """
    from server.tables import StrategyTask
    from datetime import timedelta
    now = datetime.now()
    threshold = (now - timedelta(seconds=max_idle_seconds)).isoformat(timespec="seconds")

    rows = StrategyTask.query_by_fields({"status": "running"})
    n_cleaned = 0
    for r in rows:
        task_id = r._data.get("id")
        progress_json = r._data.get("progress")
        if not progress_json:
            continue
        try:
            import json
            progress = json.loads(progress_json) if isinstance(progress_json, str) else progress_json
        except Exception:
            continue
        updated_at = progress.get("updated_at", "")
        if updated_at and updated_at >= threshold:
            continue  # 还在动, 跳过
        # 已 stale, 标 failed
        r["status"] = "failed"
        r["error_msg"] = f"task 卡在 running, progress {max_idle_seconds}s 没更新 (updated_at={updated_at})"
        r["finished_at"] = now
        r["updated_at"] = now
        # 标记 progress 为 failed
        try:
            cur = json.loads(r._data.get("progress", "{}")) if r._data.get("progress") else {}
        except Exception:
            cur = {}
        cur["phase"] = "failed"
        cur["msg"] = f"⚠️ task 卡死, 自动标记 failed (last update {updated_at})"
        cur["updated_at"] = now.isoformat(timespec="seconds")
        r["progress"] = json.dumps(cur)
        r.update()
        log.warning("sweep_stale_running_tasks: marked task=%d failed (last progress update=%s)", task_id, updated_at)
        n_cleaned += 1
    return n_cleaned


def _get_task_script_id(task_id: int) -> Optional[str]:
    """返 task 的 script_id (str, v90+ 复合 PK)"""
    from server.tables import StrategyTask
    row = StrategyTask.query_one(id=task_id)
    return getattr(row, "_data", {}).get("script_id") if row else None


def _get_task_script_pk(task_id: int) -> Optional[Tuple[int, str]]:
    """返 task 的 (user_id, script_id) 复合 PK (v90+ 复合主键用)

    Returns:
        None: task 不存在
        (user_id, script_id): 找到的复合 PK
    """
    from server.tables import StrategyTask
    row = StrategyTask.query_one(id=task_id)
    if row is None:
        return None
    data = row._data
    return (data.get("user_id"), data.get("script_id"))


def _iso(v) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, str):
        return v
    return str(v)


__all__ = [
    "list_scripts", "get_script", "create_script", "update_script", "delete_script",
    "list_tasks", "get_task", "create_task", "run_task",
    "stop_task", "delete_task", "get_task_logs", "get_task_signals", "get_task_audit",
]