"""
strategy — 行情消费 + 策略信号消费

旧网格策略引擎（Strategy / StrategyRegime / StrategyGrid / StrategyAudit）
已下线：对应 4 张表已删，
引擎 / repository / grid / regime / audit / indicators / flags / t0 模块已移除。

保留两个仍在用的服务：
  quote_consumer   — hqserver 行情 → quote_cache + 前端 WS quote_update（行情面板）
  signal_consumer  — RabbitMQ 策略信号 → 下单（新脚本策略系统）
"""
from server.services.strategy.quote_consumer import (
    QuoteConsumer, get_quote_consumer, close_quote_consumer,
)
from server.services.strategy.signal_consumer import (
    SignalConsumer, get_signal_consumer, start_signal_consumer, stop_signal_consumer,
)

__all__ = [
    "QuoteConsumer", "get_quote_consumer", "close_quote_consumer",
    "SignalConsumer", "get_signal_consumer", "start_signal_consumer", "stop_signal_consumer",
]
