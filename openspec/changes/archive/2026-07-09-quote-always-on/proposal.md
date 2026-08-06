# Quote 行情 7×24 启用：去除 STRATEGY_ENGINE_ENABLED 对行情的控制

## Why

当前行情（`QuoteConsumer`）由 `STRATEGY_ENGINE_ENABLED` 守门：

- `server/.env:30`: `STRATEGY_ENGINE_ENABLED=1`
- `server/main.py:125-136`: `on_startup_quote_consumer()` 检测 `settings.STRATEGY_ENGINE_ENABLED`，false 时直接 return

问题：行情是**所有**前端实时数据源（Holdings/Positions/Trade/QuickTrade 都用 `quote_update` WS channel 来更新市值/最新价），不是策略引擎专属。即使策略功能不用，行情也必须 7×24 拉，strategy_engine_enabled 的开关语义不对。

## What Changes

**只对 `QuoteConsumer` 启动逻辑解除 `STRATEGY_ENGINE_ENABLED` 守门，**策略 REST API（`/api/strategy/*`）保留原样（仍然需要策略引擎启用时才调用，避免调用一个未初始化的 engine）。

### 修改清单

| 文件 | 改动 | 行号 |
|---|---|---|
| `server/main.py` | `on_startup_quote_consumer()` 移除 `if not settings.STRATEGY_ENGINE_ENABLED:` 分支；保留 pytest 守门 | 125-136 |
| `server/services/strategy/quote_consumer.py` | docstring 第 11 行去掉 STRATEGY_ENGINE_ENABLED 守门描述 | 11 |
| `openspec/specs/configuration/spec.md` | 同步 `REQ-CFG-008`：去除 STRATEGY_ENGINE_ENABLED 对 QuoteConsumer 的控制描述 | 找到 REQ-CFG-008 段 |
| `openspec/specs/frontend/spec.md` | 加 `REQ-FE-520`：QuoteConsumer 7×24 启用，WS 前端 quote_update 实时更新 | 新增 |

### NOT CHANGED（保持原状,等下次工单）

- `.env:30 STRATEGY_ENGINE_ENABLED=1` —— 仍然是策略引擎的开关
- `server/config.py:104 STRATEGY_ENGINE_ENABLED` 定义 —— 策略端继续用
- `server/api/strategy/endpoints.py:38/63/75` 三个 503 守门 —— 策略 API 继续有
- `server/tests/strategy/test_api.py` —— 策略 API 的开关测试不变

## Impact

- **功能**：QuoteConsumer 总是在 backend 启动后跑，连 hqserver :8765 拉 tick，broadcast 到 ws_manager['quote_update']
- **性能**：单 WS 长连接收所有 tick（hqserver 单连接无订阅协议），本地按 stock_code 过滤再 fanout。内存和 CPU 极低
- **风险**：低。行情本来就是 at-most-once（UDP-style），丢一两条不影响市值聚合
- **测试**：现有 `test_api.py` 测试不需改，pytest mode 下 `PYTEST_CURRENT_TEST` 仍然跳过 QuoteConsumer
- **回滚**：注释回去 1 行就回滚

## Alternatives Considered

- **A'：直接删 STRATEGY_ENGINE_ENABLED 整个环境变量** —— 影响策略 API，不在本工单范围
- **A''：QuoteConsumer 启用但加 rate-limit / dedup** —— 不必要，hqserver 6/s 的速率换前端聚合 display 完全无压力
