# Spec Delta: configuration

## MODIFIED Requirements

### REQ-CFG-008: 策略引擎启用开关 `STRATEGY_ENGINE_ENABLED`

The env var `STRATEGY_ENGINE_ENABLED=1|0` 控制**策略引擎**（StrategyEngine / strategies router）的启用,**不再**控制 `QuoteConsumer`（行情消费者）的启动。

#### Scenario: 策略引擎关闭时

- **WHEN** `STRATEGY_ENGINE_ENABLED=0`
- **THEN** `POST /api/strategy/*` 返 503 + code=STRATEGY_ENGINE_DISABLED
- **AND** 策略 router 不接收报价 fanout
- **AND** **QuoteConsumer 仍然启动**（行情和策略独立）

#### Scenario: 策略引擎开启时

- **WHEN** `STRATEGY_ENGINE_ENABLED=1`
- **THEN** 策略 router 正常工作,接收报价 fanout
- **AND** QuoteConsumer 启动（与之前行为相同）
