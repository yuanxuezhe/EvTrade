"""
strategy/t0 — T0 日内做T策略模块

核心信号模型：
  1. VWAP 乖离率回归（最高胜率）
  2. 开盘30分钟冲高/急跌（捕捉早盘最大波幅）
  3. 5分钟布林线触轨突破

支持测试/实盘双模式，内置严格日内风控（止损、14:30截断、日限2次）。

Public API:
  models           — 参数数据类 (T0StrategyParams / T0Position / T0Signal)
  bar_aggregator   — tick → 5分钟K线聚合
  t0_indicators    — VWAP / 布林线 / K线形态
  signals          — 三大信号检测
  position_tracker — 日内敞口跟踪
  risk_control     — 止损 / 时间截断 / 频次限制
  engine           — T0StrategyEngine 主引擎
"""
from server.services.strategy.t0.models import (
    T0StrategyParams,
    T0VWAPParams,
    T0OpeningParams,
    T0BollingerParams,
    T0RiskParams,
    T0Position,
    T0Signal,
    T0EvaluateResult,
)
from server.services.strategy.t0.bar_aggregator import Bar, BarAggregator
from server.services.strategy.t0.t0_indicators import (
    compute_vwap,
    compute_bollinger_bands,
    compute_vwap_deviation,
    detect_lower_shadow,
    detect_zhiting_yangxian,
    detect_insufficient_volume,
)
from server.services.strategy.t0.signals import detect_all_signals
from server.services.strategy.t0.position_tracker import T0PositionTracker
from server.services.strategy.t0.risk_control import T0RiskController
from server.services.strategy.t0.engine import T0StrategyEngine

__all__ = [
    "T0StrategyParams", "T0VWAPParams", "T0OpeningParams",
    "T0BollingerParams", "T0RiskParams", "T0Position", "T0Signal",
    "T0EvaluateResult",
    "Bar", "BarAggregator",
    "compute_vwap", "compute_bollinger_bands", "compute_vwap_deviation",
    "detect_lower_shadow", "detect_zhiting_yangxian", "detect_insufficient_volume",
    "detect_all_signals",
    "T0PositionTracker",
    "T0RiskController",
    "T0StrategyEngine",
]
