"""
server/api/script_strategy/schemas/tasks.py — Task 端点 Pydantic 模型

职责单一: 任务 (Task) 的响应 schema, 无业务逻辑。
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class TaskOut(BaseModel):
    id: int
    user_id: int
    strategy_id: Optional[int] = None  # 挂策略不挂脚本
    batch_no: Optional[int] = None     # 批次号 (序号表 task_batch)
    description: str = ""
    stock_code: str
    mode: Optional[str] = None
    status: str
    params: Dict[str, Any] = {}
    backtest_result: Optional[Dict[str, Any]] = None
    backtest_start_date: Optional[str] = None
    backtest_end_date: Optional[str] = None
    period: Optional[str] = None
    fields: Optional[str] = None
    pnl: float = 0.0
    positions: Optional[Dict[str, Any]] = None
    trades_count: int = 0
    live_signals: List[Dict[str, Any]] = []
    progress: Optional[Dict[str, Any]] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error_msg: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    backtest_metric_value: Optional[float] = None
