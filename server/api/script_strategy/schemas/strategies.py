"""
server/api/script_strategy/schemas/strategies.py — Strategy / 回测 / 批次 Pydantic 模型

职责单一: 策略 (Strategy) 与回测批次 (BacktestRequest/Response/BatchOut) 的请求与响应 schema, 无业务逻辑。
"""
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


# ─────────────── Strategy / 回测 / 批次 ───────────────


class StrategyCreate(BaseModel):
    name: str
    script_id: str  # 脚本 id 是用户自命名 varchar
    stock_code: str  # 必填: 策略绑定标的, 只针对此标的回测


class StrategyUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = Field(None, pattern="^(draft|active|archived)$")
    is_public: Optional[bool] = None  # 公开/私有开关 (仅 owner)


class StrategyOut(BaseModel):
    strategy_id: int
    user_id: int
    script_id: str
    name: str
    status: str
    is_public: bool = False  # 显式可见性
    stock_code: Optional[str] = None  # 绑定标的
    best_params: Optional[Dict[str, Any]] = None
    script: Optional[Dict[str, Any]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class BacktestRequest(BaseModel):
    """回测请求: mode=single (params) 或 mode=sweep (param_ranges)"""
    mode: str = Field("single", pattern="^(single|sweep)$")
    stock_code: Optional[str] = None  # 标的由策略绑定决定, 提供且不匹配 → 400 STOCK_MISMATCH
    backtest_start_date: str = Field(..., description="YYYYMMDD")
    backtest_end_date: str = Field(..., description="YYYYMMDD")
    # single
    params: Optional[Dict[str, Any]] = None
    # sweep (类型驱动: int/float start/end/step 含端点, choice values, string 固定)
    param_ranges: Optional[Dict[str, Dict[str, Any]]] = None
    period: Optional[str] = Field(None, pattern="^(1d|1m|5m|15m|30m|60m)$")
    fields: Optional[str] = None
    metric: str = Field("sharpe", pattern="^(sharpe|total_return|calmar)$")
    concurrency: int = Field(2, ge=1, le=16)


class BacktestResponse(BaseModel):
    batch_no: int
    total_runs: int
    mode: str
    metric: str
    over_soft_limit: bool = False
    msg: str = "backtest accepted, running in background"


class BatchOut(BaseModel):
    batch_no: Optional[int]
    created_at: Optional[str] = None
    mode: Optional[str] = None
    task_count: int = 0
    finished_count: int = 0
    failed_count: int = 0
    abandoned_count: int = 0       # 重测废弃的 task 数
    abandoned: bool = False        # 批次已被重测替代 (全部 task 废弃)
    metric: str = "sharpe"         # 批次排序指标 (sweep top1 选择)
    best_params: Optional[Dict[str, Any]] = None
    best_metric_value: Optional[float] = None
