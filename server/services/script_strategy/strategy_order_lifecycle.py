"""
server/services/script_strategy/strategy_order_lifecycle.py — 母单启停

职责单一: 母单 start/stop + 转发 payload 构造 (与 strategy_orders.py 拆分, 行数约束).
- start_strategy_order: 校验 + create_task(mode='live') + 改母单 status=running + 返回 forward_payload
- stop_strategy_order: 校验 running + 清 active_task_id + 返回 stop_url
- build_start_forward_payload: 构造 strategy_exec /internal/run-task payload
- _load_owned_order: 共享权限读取 (owner/admin)
"""
from datetime import datetime
from typing import Any, Dict

from server.services.script_strategy._convert import json_loads
from server.services.script_strategy.access import require_strategy_order_access
from server.services.script_strategy.errors import StrategyError
from server.services.script_strategy.strategy_order_convert import (
    strategy_order_row_to_dict,
)
from server.services.script_strategy.strategy_orders import (
    STATUS_CLOSED,
    STATUS_RUNNING,
    STATUS_STOPPED,
    get_strategy_order,
)
from server.services.script_strategy.tasks import create_task


# ─────────────── 错误快捷方式 ───────────────

def _not_found(order_id: int) -> StrategyError:
    return StrategyError("STRATEGY_ORDER_NOT_FOUND", f"strategy_order id={order_id} 不存在或无权访问")


def _invalid_state(current: str, action: str) -> StrategyError:
    return StrategyError(
        "STRATEGY_ORDER_INVALID_STATE",
        f"母单状态 {current!r} 不允许 {action} (要求: closed 不可 start, running 不可再 start/close)",
    )


# ─────────────── 内部 helper ───────────────

def _load_owned_order(order_id: int, user_id: int, is_admin: bool = False):
    """读母单行; 不可见 / 不存在 → STRATEGY_ORDER_NOT_FOUND. 与 access.py 语义一致."""
    from server.tables import StrategyOrder
    row = StrategyOrder.query_one(id=order_id)
    if row is None:
        raise _not_found(order_id)
    d = getattr(row, "_data", {})
    if not is_admin and d.get("user_id") != user_id:
        raise _not_found(order_id)
    return row


# ─────────────── 服务函数 ───────────────

def _verify_can_start(d: Dict[str, Any]) -> None:
    """校验母单 status 允许 start. closed / running 拒 (raise)."""
    if d["status"] == STATUS_CLOSED:
        raise _invalid_state(d["status"], "start")
    if d["status"] == STATUS_RUNNING:
        raise _invalid_state(d["status"], "start (已在运行)")


def _build_live_task(user_id: int, d: Dict[str, Any], sd: Dict[str, Any], best_params: Dict[str, Any]) -> int:
    """建 1 行 live strategy_task (mode='live', status='queued'). 返回 live_task_id."""
    live_task = create_task(
        user_id=user_id,
        strategy_id=d["strategy_id"],
        stock_code=d["stock_code"],
        params=best_params,
        description=sd.get("name", "") or f"strategy-{d['strategy_id']}",
        mode="live",
        status="queued",
    )
    return live_task["id"]


def _apply_running_state(order_id: int, d: Dict[str, Any], live_task_id: int) -> None:
    """改母单 status=running + active_task_id + run_count+1 + last_started_at."""
    from server.tables import StrategyOrder
    now = datetime.now()
    StrategyOrder.update_one(
        {
            "status": STATUS_RUNNING,
            "active_task_id": live_task_id,
            "run_count": (d.get("run_count") or 0) + 1,
            "last_started_at": now,
            "updated_at": now,
        },
        id=order_id,
    )


def start_strategy_order(
    order_id: int, user_id: int, is_admin: bool = False,
) -> Dict[str, Any]:
    """启动母单实盘: 校验状态 + best_params → create_task(mode='live') → 转发 strategy_exec.

    注意: 不在本函数内 await HTTP — 转发由 api 层处理 (fastapi Depends).
    本函数仅编排: (1) 校验 (2) 建 strategy_task live 行 (3) 改母单 status=running +
    active_task_id + run_count+1 + last_started_at. 实际转发 payload 由
    `build_start_forward_payload(strategy_order, strategy, best_params, live_task_id)` 生成。

    Raises:
        StrategyError: STRATEGY_ORDER_NOT_FOUND / STRATEGY_ORDER_INVALID_STATE / NO_BEST_PARAMS
    """
    from server.tables import StrategyOrder

    order = _load_owned_order(order_id, user_id, is_admin=is_admin)
    d = strategy_order_row_to_dict(order)
    _verify_can_start(d)

    strat = require_strategy_order_access(d["strategy_id"], user_id, is_admin=is_admin)
    sd = getattr(strat, "_data", {})
    best_params = json_loads(sd.get("best_params"))
    if not best_params:
        raise StrategyError("NO_BEST_PARAMS", "策略尚未回测出最佳参数, 不可启动实盘")

    live_task_id = _build_live_task(user_id, d, sd, best_params)
    _apply_running_state(order_id, d, live_task_id)

    refreshed = get_strategy_order(order_id, user_id, is_admin=is_admin) or {}
    return {
        "task_id": d["task_id"],
        "status": STATUS_RUNNING,
        "active_task_id": live_task_id,
        "strategy_name": sd.get("name", ""),
        "forward_payload": build_start_forward_payload(
            strategy_order_row_to_dict(StrategyOrder.query_one(id=order_id)),
            sd,
            best_params,
            live_task_id,
        ),
        "order": refreshed,
    }


def stop_strategy_order(
    order_id: int, user_id: int, is_admin: bool = False,
) -> Dict[str, Any]:
    """停止母单实盘: 校验 running+active_task_id → 改 status=stopped.

    实际转发 /internal/stop-task 由 api 层处理 (同 start).
    Returns payload 含 stop_url + active_task_id 给 api 层用。

    Raises:
        StrategyError: STRATEGY_ORDER_NOT_FOUND / STRATEGY_ORDER_INVALID_STATE
    """
    from server.tables import StrategyOrder

    order = _load_owned_order(order_id, user_id, is_admin=is_admin)
    d = strategy_order_row_to_dict(order)
    if d["status"] != STATUS_RUNNING:
        raise _invalid_state(d["status"], "stop")
    active_task_id = d.get("active_task_id")
    if not active_task_id:
        raise StrategyError("STRATEGY_ORDER_INVALID_STATE", "母单 running 但无 active_task_id, 请联系管理员")

    now = datetime.now()
    StrategyOrder.update_one(
        {
            "status": STATUS_STOPPED,
            "active_task_id": None,
            "last_stopped_at": now,
            "updated_at": now,
        },
        id=order_id,
    )
    return {
        "task_id": d["task_id"],
        "status": STATUS_STOPPED,
        "active_task_id": active_task_id,
        "stop_url": f"/internal/stop-task",  # api 层拼 base URL
    }


def build_start_forward_payload(
    order: Dict[str, Any], strategy: Dict[str, Any], best_params: Dict[str, Any], live_task_id: int,
) -> Dict[str, Any]:
    """构造 strategy_exec /internal/run-task payload (母单实盘路径).

    关键字段:
    - mode='live'
    - task_id=live_task_id (strategy_task.id, 母单 active_task_id 指向它)
    - parent_task_id=order['task_id']  (母单对外编号, signal payload 透传到 signal_consumer)
    - strategy_name=strategy.get('name', '')  (子单 user_def)
    """
    return {
        "task_id": live_task_id,
        "user_id": order["user_id"],
        "strategy_id": order["strategy_id"],
        "script_id": strategy.get("script_id", ""),
        "stock_code": order["stock_code"],
        "mode": "live",
        "params": best_params,
        "parent_task_id": order["task_id"],      # 母单归因
        "strategy_name": strategy.get("name", ""),  # 子单 user_def
    }


__all__ = [
    "start_strategy_order", "stop_strategy_order", "build_start_forward_payload",
]
