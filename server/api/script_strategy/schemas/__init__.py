"""
server/api/script_strategy/schemas — REST 端点 Pydantic 请求/响应模型聚合入口

按子模块拆分:
- scripts.py          → ParamSpec / ScriptCreate / ScriptUpdate / ScriptOut
- tasks.py            → TaskOut
- strategies.py       → StrategyCreate/Update/Out / BacktestRequest/Response / BatchOut
- strategy_orders.py  → StrategyOrderCreate/Out / StartStopResponse

外部统一通过 `from server.api.script_strategy.schemas import <Class>` 导入, 兼容原单文件路径。
"""
from server.api.script_strategy.schemas.scripts import (
    ParamSpec,
    ScriptCreate,
    ScriptOut,
    ScriptUpdate,
)
from server.api.script_strategy.schemas.strategies import (
    BacktestRequest,
    BacktestResponse,
    BatchOut,
    StrategyCreate,
    StrategyOut,
    StrategyUpdate,
)
from server.api.script_strategy.schemas.strategy_orders import (
    StartStopResponse,
    StrategyOrderCreate,
    StrategyOrderOut,
)
from server.api.script_strategy.schemas.tasks import TaskOut

__all__ = [
    # scripts
    "ParamSpec",
    "ScriptCreate",
    "ScriptUpdate",
    "ScriptOut",
    # tasks
    "TaskOut",
    # strategies
    "StrategyCreate",
    "StrategyUpdate",
    "StrategyOut",
    "BacktestRequest",
    "BacktestResponse",
    "BatchOut",
    # strategy_orders
    "StrategyOrderCreate",
    "StrategyOrderOut",
    "StartStopResponse",
]
