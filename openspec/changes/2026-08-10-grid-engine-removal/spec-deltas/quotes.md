# spec-delta: quotes（现有 spec 增量）

## MODIFIED Requirements

### REQ-QUOTE-005: 后端 WS 接入（QuoteConsumer）— 去掉网格引擎耦合

> **变更说明（2026-08-10）**：commit `aa70dae` 重写了 `server/services/strategy/quote_consumer.py`（v124），移除 `StrategyEngine` / `T0StrategyEngine` / `load_engines` / `evaluate_tick` / `subscribe_strategy`，保留纯行情职责：hqserver WS → `quote_cache` 快照 → `broadcast_to_stock` 推前端 `/ws/quote_update`。

REQ-QUOTE-005 更新内容：

- **职责**：从"fan-out 到 StrategyEngine"改为"写 `quote_cache` + 广播 `quote_update`"（持久化由 `main.py` periodic flush task 负责）
- **删除**：`STRATEGY_ENGINE_ENABLED` 启动控制（config 已删）、`prev_close` 注入 engine（引擎已删）
- **Scenario 更新**：删除"灰度门关闭时不启动"、"tick fan-out 到匹配 engine"；新增"tick 写快照 + 广播 quote_update"

## 保留（未变）

- REQ-QUOTE-006（WS 订阅 pattern 化）及其余行情契约
- 重连退避 / 60s 无 tick 警告 / 优雅停机场景
