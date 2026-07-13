# Spec Delta: frontend

## ADDED Requirements

### REQ-FE-520: QuoteConsumer 7×24 启用（与策略引擎解耦，2026-07-09 重构）

`backend.QuoteConsumer` 在 FastAPI startup 后**无条件**启动，连 `ws://127.0.0.1:8765` 拉 tick，broadcast 到 `ws_manager['quote_update']`。

#### Scenario: 策略引擎关闭但页面打开

- **WHEN** `.env` 中 `STRATEGY_ENGINE_ENABLED=0`,前端打开 Holdi