"""
server/api/script_strategy/schemas/strategy_orders.py — 策略下单母单 Pydantic 模型

职责单一: 策略母单 (StrategyOrder) 与 start/stop 响应的请求与响应 schema, 无业务逻辑。
"""
from typing import Any, Dict, Optional

from pydantic import BaseModel


# ─────────────── 策略下单母单 ───────────────


class StrategyOrderCreate(BaseModel):
    strategy_id: int


class StrategyOrderOut(BaseModel):
    id: int
    task_id: int
    user_id: int
    strategy_id: int
    strategy_name: Optional[str] = None
    stock_code: str = ""
    status: str = "stopped"
    active_task_id: Optional[int] = None
    run_count: int = 0
    children_count: int = 0
    last_started_at: Optional[str] = None
    last_stopped_at: Optional[str] = None
    closed_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class StartStopResponse(BaseModel):
    """母单 start/stop 响应: task_id + status + 转发提示字段.

    api 层根据 forward_payload / stop_url 转发到 strategy_exec。
    """
    task_id: int
    status: str
    active_task_id: Optional[int] = None
    strategy_name: Optional[str] = None
    forward_payload: Optional[Dict[str, Any]] = None
    stop_url: Optional[str] = None
