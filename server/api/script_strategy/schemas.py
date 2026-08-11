"""
server/api/script_strategy/schemas.py — REST 端点 Pydantic 请求/响应模型 (v123)

职责单一: 脚本 / 策略 / 任务 / 回测批次 端点的请求与响应 schema, 无业务逻辑。
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ─────────────── Script ───────────────


class ParamSpec(BaseModel):
    key: str
    type: str = Field("int", pattern="^(int|float|choice)$")
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None
    default: Any = None
    values: Optional[List[Any]] = None


class ScriptCreate(BaseModel):
    name: str
    code: str
    params_schema: List[ParamSpec] = []
    description: str = ""
    is_public: bool = False  # v90+ 是否公开 (其他用户可见)


class ScriptUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    params_schema: Optional[List[ParamSpec]] = None
    description: Optional[str] = None
    status: Optional[str] = None
    is_public: Optional[bool] = None  # v90+ 可改公开状态


class ScriptOut(BaseModel):
    id: str  # v90+ 复合 PK: (user_id, id), id 字符串 (用户自命名)
    user_id: int
    name: str
    code: str
    params_schema: List[Dict[str, Any]] = []
    description: str = ""
    status: str
    is_public: bool = False
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class TaskOut(BaseModel):
    id: int
    user_id: int
    strategy_id: Optional[int] = None  # v123: 挂策略不挂脚本
    batch_no: Optional[int] = None     # v123: 批次号 (序号表 task_batch)
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


# ─────────────── Strategy / 回测 / 批次 ───────────────


class StrategyCreate(BaseModel):
    name: str
    script_id: str  # v90+ 脚本 id 是用户自命名 varchar
    stock_code: str  # v125 必填: 策略绑定标的, 只针对此标的回测


class StrategyUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = Field(None, pattern="^(draft|active|archived)$")
    is_public: Optional[bool] = None  # v125 公开/私有开关 (仅 owner)


class StrategyOut(BaseModel):
    strategy_id: int
    user_id: int
    script_id: str
    name: str
    status: str
    is_public: bool = False  # v125 显式可见性
    stock_code: Optional[str] = None  # v125 绑定标的
    best_params: Optional[Dict[str, Any]] = None
    script: Optional[Dict[str, Any]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class BacktestRequest(BaseModel):
    """回测请求: mode=single (params) 或 mode=sweep (param_ranges)"""
    mode: str = Field("single", pattern="^(single|sweep)$")
    stock_code: Optional[str] = None  # v125: 标的由策略绑定决定, 提供且不匹配 → 400 STOCK_MISMATCH
    backtest_start_date: str = Field(..., description="YYYYMMDD")
    backtest_end_date: str = Field(..., description="YYYYMMDD")
    # single
    params: Optional[Dict[str, Any]] = None
    # sweep (v123 D5 类型驱动: int/float start/end/step 含端点, choice values, string 固定)
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
    abandoned_count: int = 0       # v124: 重测废弃的 task 数
    abandoned: bool = False        # v124: 批次已被重测替代 (全部 task 废弃)
    metric: str = "sharpe"         # v124: 批次排序指标 (sweep top1 选择)
    best_params: Optional[Dict[str, Any]] = None
    best_metric_value: Optional[float] = None


# ─────────────── 策略下单母单 (v126) ───────────────


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
