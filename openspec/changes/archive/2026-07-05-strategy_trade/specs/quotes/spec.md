## ADDED Requirements

### Requirement: 后端策略引擎 WS 客户端接入（REQ-QUOTE-003）

`server/services/strategy/quote_consumer.py::QuoteConsumer` 作为后端**首个**行情消费者，通过 `HQ_WS_URL` env（默认 `ws://localhost:8765/ws/quote`）接入 hqserver WebSocket，独立于前端 Vue 直连。

> 现有架构约束（AGENTS.md §数据流）：行情由 hqserver 解耦到独立 WebSocket 服务（:8765），Vue 直连。本 change 不修改 hqserver，只在 backend 增加 WS 客户端订阅。

#### Scenario: QuoteConsumer 启动 + 接收 tick

- **WHEN** `STRATEGY_ENGINE_ENABLED=true` + 后端启动
- **THEN** QuoteConsumer MUST 建立到 `HQ_WS_URL` 的 WebSocket 连接
- **AND** 收到 hqserver tick message（MOVE_FAST 协议，`{code, last_price, ...}`）→ 调对应 StrategyEngine.evaluate_tick

#### Scenario: 断线指数退避重连

- **WHEN** hqserver 关闭 / 网络中断
- **THEN** QuoteConsumer MUST 按 1s → 2s → 4s → 8s → 16s → 30s（max）无限重试，每次重连成功 INFO log

#### Scenario: STRATEGY_ENGINE_ENABLED=false 不启动

- **WHEN** `.env` 中 `STRATEGY_ENGINE_ENABLED=false`（默认）
- **THEN** QuoteConsumer MUST NOT 创建 asyncio task，后端无 WS 连接

#### Scenario: 与前端直连并行不冲突

- **WHEN** QuoteConsumer（后端）+ Vue（前端）同时订阅 600519.SH
- **THEN** 两条连接互不感知，hqserver 正常 FANOUT（hqserver 行为不变）
- **AND** 策略引擎评估走后端 QuoteConsumer，Vue UI 实时报价走前端直连，两条路径独立