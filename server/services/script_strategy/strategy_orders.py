"""
server/services/script_strategy/strategy_orders.py — 策略母单 (v126, CRUD 部分)

职责单一: strategy_order 实体业务逻辑 — 查询 + 创建 + 关闭.
- 启停 (start/stop) + 转发 payload 构造 → strategy_order_lifecycle.py (拆分, 行数约束)
- 6 个 CRUD 服务函数 + 状态机常量 (stopped / running / closed)
- 复用 access.py 的 resolve_strategy / require_strategy_order_access
- best_params 门禁: 无 best_params 不可建 (v122 实盘门禁延续)

不启动任何引擎线程: 启动实盘 = 建 1 行 live strategy_task + 转发 strategy_exec。
stop 时调用 /internal/stop-task 异步停止, 状态由前端轮询刷新。
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from server.repo.orders import next_seq
from server.services.script_strategy._convert import (
    iso,
    json_loads,
)
from server.services.script_strategy.access import (
    require_strategy_order_access,
    resolve_strategy,
)
from server.services.script_strategy.errors import StrategyError
from server.services.script_strategy.strategy_order_convert import (
    strategy_order_row_to_dict,
)


# ─────────────── 状态机常量 ───────────────

STATUS_STOPPED = "stopped"
STATUS_RUNNING = "running"
STATUS_CLOSED = "closed"
ALL_STATUSES = (STATUS_STOPPED, STATUS_RUNNING, STATUS_CLOSED)


# ─────────────── 错误快捷方式 ───────────────

def _not_found(order_id: int) -> StrategyError:
    return StrategyError("STRATEGY_ORDER_NOT_FOUND", f"strategy_order id={order_id} 不存在或无权访问")


# ─────────────── 服务函数 ───────────────

def list_strategy_orders(user_id: int, is_admin: bool = False) -> List[Dict[str, Any]]:
    """列我的母单 (admin 全部); JOIN 策略名 + 子单数 COUNT (子单按 orders.task_id=母单.task_id)."""
    from server.tables import Orders, StrategyOrder

    if is_admin:
        rows = StrategyOrder.query_all(order="desc")
    else:
        rows = StrategyOrder.query_by_fields({"user_id": user_id}, order="desc")

    out = []
    for r in rows:
        d = strategy_order_row_to_dict(r)
        # 子单数 (orders.task_id = 母单.task_id AND strategy_type = 2)
        children = Orders.query_by_fields(
            {"task_id": d["task_id"], "strategy_type": 2},
            columns=["trd_date", "order_no"],
        )
        d["children_count"] = len(children)
        # 拼策略名 (owner/admin 看到完整策略名; 他人公开策略名也返)
        strat = resolve_strategy(d["strategy_id"], user_id, is_admin=is_admin)
        if strat is not None:
            sd = getattr(strat, "_data", {})
            d["strategy_name"] = sd.get("name", "")
        else:
            d["strategy_name"] = None
        out.append(d)
    return out


def get_strategy_order(
    order_id: int, user_id: int, is_admin: bool = False,
) -> Optional[Dict[str, Any]]:
    """母单详情. 不可见 / 不存在 → None."""
    from server.tables import StrategyOrder
    row = StrategyOrder.query_one(id=order_id)
    if row is None:
        return None
    d = strategy_order_row_to_dict(row)
    if not is_admin and d.get("user_id") != user_id:
        return None
    strat = resolve_strategy(d["strategy_id"], user_id, is_admin=is_admin)
    if strat is not None:
        d["strategy_name"] = getattr(strat, "_data", {}).get("name", "")
    return d


def list_strategy_order_children(
    order_id: int, user_id: int, is_admin: bool = False,
) -> Optional[List[Dict[str, Any]]]:
    """母单子单列表 (orders.task_id=母单.task_id, strategy_type=2). 不可见 / 不存在 → None.

    透传 holdings.orders 字段结构 (前端 holdings store 已用),
    不再二次封装, 避免与 HoldingsView 字段命名漂移。
    """
    from server.tables import Orders
    order = get_strategy_order(order_id, user_id, is_admin=is_admin)
    if order is None:
        return None
    # 拉所有该 task_id 的 strategy_type=2 单 (轻量列)
    cols = (
        "trd_date", "order_no", "order_id", "user_def", "stock_code",
        "order_type", "price_type", "price", "volume", "traded_volume",
        "traded_amount", "avg_price", "cancelled_volume", "order_flag",
        "status", "status_msg", "order_time", "task_id", "strategy_type",
        "created_at", "updated_at", "pushed_at",
    )
    rows = Orders.query_by_fields(
        {"task_id": order["task_id"], "strategy_type": 2},
        columns=cols,
    )
    rows.sort(key=lambda r: getattr(r, "_data", {}).get("order_time", "") or "", reverse=True)
    return [_order_row_minimal(r) for r in rows]


def _order_row_minimal(row) -> Dict[str, Any]:
    """orders 行 → 子单展示 dict (前端 holdings.orders 兼容字段)."""
    d = getattr(row, "_data", {})
    return {
        "trd_date": d.get("trd_date"),
        "order_no": d.get("order_no"),
        "order_id": d.get("order_id"),
        "user_def": d.get("user_def", ""),
        "stock_code": d.get("stock_code"),
        "order_type": d.get("order_type"),
        "price_type": d.get("price_type"),
        "price": d.get("price", 0.0) or 0.0,
        "volume": d.get("volume", 0) or 0,
        "traded_volume": d.get("traded_volume", 0) or 0,
        "traded_amount": d.get("traded_amount", 0.0) or 0.0,
        "avg_price": d.get("avg_price", 0.0) or 0.0,
        "cancelled_volume": d.get("cancelled_volume", 0) or 0,
        "order_flag": d.get("order_flag", 0) or 0,
        "status": d.get("status"),
        "status_msg": d.get("status_msg", ""),
        "order_time": d.get("order_time"),
        "task_id": d.get("task_id"),
        "strategy_type": d.get("strategy_type", 0) or 0,
        "created_at": iso(d.get("created_at")),
        "updated_at": iso(d.get("updated_at")),
    }


def create_strategy_order(strategy_id: int, user_id: int, is_admin: bool = False) -> Dict[str, Any]:
    """创建母单 (status=stopped). 校验 owner / best_params 非空.

    Raises:
        StrategyError: NO_STRATEGY (他人私有/不存在) / NO_BEST_PARAMS
    """
    from server.tables import StrategyOrder

    strat = require_strategy_order_access(strategy_id, user_id, is_admin=is_admin)
    sd = getattr(strat, "_data", {})
    best_params = json_loads(sd.get("best_params"))
    if not best_params:
        raise StrategyError("NO_BEST_PARAMS", "策略尚未回测出最佳参数, 不可建母单")

    task_id = int(next_seq("strategy_order"))
    now = datetime.now()
    data = {
        "task_id": task_id,
        "user_id": user_id,
        "strategy_id": strategy_id,
        "stock_code": sd.get("stock_code", ""),
        "status": STATUS_STOPPED,
        "active_task_id": None,
        "run_count": 0,
        "last_started_at": None,
        "last_stopped_at": None,
        "closed_at": None,
        "created_at": now,
        "updated_at": now,
    }
    row = StrategyOrder.add_one(data)
    return strategy_order_row_to_dict(row)


def close_strategy_order(
    order_id: int, user_id: int, is_admin: bool = False,
) -> Dict[str, Any]:
    """关闭母单 (终态, 保审计, 不硬删). 校验非 running.

    Raises:
        StrategyError: STRATEGY_ORDER_NOT_FOUND / STRATEGY_ORDER_INVALID_STATE
    """
    from server.tables import StrategyOrder

    row = StrategyOrder.query_one(id=order_id)
    if row is None:
        raise _not_found(order_id)
    d = strategy_order_row_to_dict(row)
    if not is_admin and d.get("user_id") != user_id:
        raise _not_found(order_id)
    if d["status"] == "running":
        raise StrategyError(
            "STRATEGY_ORDER_INVALID_STATE",
            f"母单状态 {d['status']!r} 不允许 close (要求: closed 不可 start, running 不可再 start/close)",
        )

    now = datetime.now()
    StrategyOrder.update_one(
        {
            "status": STATUS_CLOSED,
            "closed_at": now,
            "updated_at": now,
        },
        id=order_id,
    )
    return get_strategy_order(order_id, user_id, is_admin=is_admin) or {}


__all__ = [
    "STATUS_STOPPED", "STATUS_RUNNING", "STATUS_CLOSED", "ALL_STATUSES",
    "list_strategy_orders", "get_strategy_order", "list_strategy_order_children",
    "create_strategy_order", "close_strategy_order",
]
