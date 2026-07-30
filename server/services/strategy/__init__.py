"""
strategy — 网格策略交易引擎

📖 详细 spec：openspec/specs/strategy/spec.md（13 REQ）
📖 数据契约：openspec/specs/data-model/spec.md §2.4

Public API（facade 模式）：
  models   — 4 张 ORM（Strategy / StrategyRegime / StrategyGrid / StrategyAudit）
  repository — DB CRUD
  indicators — 指标计算（MA / RSI / MACD / VolAvg + IndicatorParams 配置集）
  flags    — 标志检测器（v1 硬编码 9 种）
  regime   — 参数集匹配（priority + required AND + exclude NOT + cooldown）
  grid     — 网格决策（plan_buy / plan_sell 含底仓保护 / plan_clear）
  audit    — 触发审计写入（write_audit wrapper）
  engine   — 评估入口（StrategyEngine，tick 驱动 + WS broadcast）
  quote_consumer — 后端 WS 客户端（接 hqserver）
  t0       — T0 日内做T策略模块（VWAP / 开盘冲跌 / 布林线）
"""
from server.services.strategy.models import (
    Strategy,
    StrategyRegime,
    StrategyGrid,
    StrategyAudit,
)
from server.services.strategy import repository  # noqa: F401  # 触发 re-export
from server.services.strategy.indicators import (  # noqa: F401
    IndicatorParams, TickBuffer,
    compute_ma, compute_rsi, compute_macd, compute_vol_avg,
)
from server.services.strategy.flags import (  # noqa: F401
    FLAG_REGISTRY, FlagDef, detect_flags, get_flag_definitions,
)
from server.services.strategy.regime import (  # noqa: F401
    match_regime, apply_cooldown, COOLDOWN_SECONDS,
)
from server.services.strategy.grid import (  # noqa: F401
    GridAction, plan_buy, plan_sell, plan_clear, evaluate_grids, LOT_SIZE,
)
from server.services.strategy.audit import write_audit  # noqa: F401
from server.services.strategy.engine import (  # noqa: F401
    StrategyEngine, EvaluateResult, STRATEGY_WS_CHANNEL,
)
from server.services.strategy.quote_consumer import (  # noqa: F401
    QuoteConsumer, get_quote_consumer, close_quote_consumer,
)
from server.services.strategy.t0 import (  # noqa: F401
    T0StrategyParams, T0StrategyEngine, T0EvaluateResult,
)

__all__ = [
    "Strategy", "StrategyRegime", "StrategyGrid", "StrategyAudit",
    "repository",
    "IndicatorParams", "TickBuffer",
    "compute_ma", "compute_rsi", "compute_macd", "compute_vol_avg",
    "FLAG_REGISTRY", "FlagDef", "detect_flags", "get_flag_definitions",
    "match_regime", "apply_cooldown", "COOLDOWN_SECONDS",
    "GridAction", "plan_buy", "plan_sell", "plan_clear", "evaluate_grids", "LOT_SIZE",
    "write_audit",
    "StrategyEngine", "EvaluateResult", "STRATEGY_WS_CHANNEL",
    "QuoteConsumer", "get_quote_consumer", "close_quote_consumer",
    "T0StrategyParams", "T0StrategyEngine", "T0EvaluateResult",
]