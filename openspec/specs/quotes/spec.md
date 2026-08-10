# quotes — 行情数据分发

## Purpose

QMT 柜台通过 FANOUT exchange `quota.exchange` 推送行情快照。
`hq/hqserver.py` 订阅后双路转发：
- **(a)** 旧版兼容：republish 到 `quota.broadcast.exchange` (Topic, routing_key=stock_code)
- **(b)** 前端直连：内置 WebSocket :8765，JSON 推送

## Requirements

### REQ-QUOTE-001: 高吞吐消费

- aio-pika `iterator(no_ack=False)` + 显式 `message.ack()`
- 内部 `asyncio.Queue` 缓冲区（默认 maxsize=5000）做背压
- 4 个固定 worker 协程（`NUM_WORKERS` env 可调）
- 缓冲满后 aio-pika iterator 自然阻塞，防止内存爆

### REQ-QUOTE-002: 字段提取

- 原始 body 是 GBK 编码，格式：`stock_code|datetime|last_price|...`
- 切前两段即可得 `stock_code` 和 `last_price`，第三段不是数字则 `last_price=null`
- GBK 解码失败 → 回退 UTF-8（`errors="replace"`）

### REQ-QUOTE-003: 前端直连

- WebSocket 路径：`ws://<host>:8765`
- 客户端不发消息，服务器只 push
- 关闭连接后自动从 `_ws_clients` 移除
- 死连接（send 抛异常）清理

### REQ-QUOTE-004: 配置可调

- `HQ_RABBITMQ_URL` / `HQ_EXCHANGE_NAME` / `HQ_SOURCE_QUEUE` / `HQ_BROADCAST_EXCHANGE`
- `HQ_NUM_WORKERS` / `HQ_MAX_QUEUE_SIZE` / `HQ_PREFETCH_COUNT` / `HQ_WS_HOST` / `HQ_WS_PORT`
- 配置从 `server/.env` 加载（与 FastAPI 后端共享）

### REQ-QUOTE-005: 后端 WS 接入（QuoteConsumer）

- **`QuoteConsumer`**（`server/services/strategy/quote_consumer.py`）— 后端接入 hqserver WebSocket，**行情快照 + 前端推送**（v124 起不再耦合策略引擎）
- **单连接广播模型**：hqserver **不支持** subscribe/unsubscribe（无条件广播），QuoteConsumer 全收 tick
- **核心职责**：解析 tick → 写 `quote_cache`（内存快照，持久化由 `main.py` periodic flush task 负责）→ `broadcast_to_stock` 推前端 WS `/ws/quote_update`（行情面板实时刷新）
- **连接配置**：`HQ_WS_URL`（默认 `ws://127.0.0.1:8765`，与 hqserver 同机部署时无需修改）
- **生命周期**：模块级 singleton `_quote_consumer` + `get_quote_consumer()` / `close_quote_consumer()`（仿 RPClient 模式）
- **启动**：app startup 后**无条件**启动（无灰度门；`STRATEGY_ENGINE_ENABLED` 已删）
- **优雅停机**：`stop()` 设 `_stop` Event + `await ws.close()`
- **重连退避**：指数退避 1s → 2s → 4s → 8s → 16s → 30s (cap)
- **健康检查**：30s 心跳 log（累计 tick 数）+ 60s 无 tick 警告（**不**主动重连，连接是活的）

> **变更说明（2026-08-10，commit `aa70dae`）**：原"fan-out 到 `StrategyEngine` / `prev_close` 注入 / `STRATEGY_ENGINE_ENABLED` 启动控制"均随旧网格策略引擎删除。QuoteConsumer 现只做行情快照 + `quote_update` 广播，与策略引擎完全解耦。

#### Scenario: 重连指数退避

- **WHEN** connect 失败
- **THEN** delay 序列 MUST 是 1s → 2s → 4s → 8s → 16s → 30s (cap)

#### Scenario: 60s 无 tick 警告

- **GIVEN** 连接活跃
- **WHEN** 60s 内无 tick
- **THEN** MUST log warning（**不**主动重连）

#### Scenario: 优雅停机

- **WHEN** stop()
- **THEN** `_stop.set()` → connect_loop 退出 + consume_loop 退出 + ws.close()

#### Scenario: tick 写快照 + 广播 quote_update

- **WHEN** 收到任意 tick
- **THEN** MUST 写入 `quote_cache`（内存快照）
- **AND** `broadcast_to_stock(stock_code, tick)` 推前端 `/ws/quote_update`（按订阅 pattern fan-out，见 REQ-QUOTE-006）
- **AND** 更新 `_latest_price[stock_code]`

### REQ-QUOTE-006: WS 订阅 pattern 化（quote-pattern-subscribe 2026-07-10）

- **数据结构**：`subscription_index` 由 `Dict[stock_code, Set[ws]]` 升级为 `Dict[pattern, Set[ws]]`
- **匹配规则**：服务端用 `match_pattern(stock_code, pattern) = (pattern in stock_code)` 一行规则统一所有 case
  - `''` → 全市场（空字符串是任何字符串的子串，永远 True）
  - `'SZ'` / `'SH'` → 该后缀市场的全部代码
  - `'000001'` → 包含 `000001` 的代码（SH/SZ 双边都覆盖）
  - `'000001.SZ'` → 精确匹配该代码
- **协议**：客户端仍发 `{type:"subscribe", stock_codes:[patterns...]}`
- **subscribe_ack 增强**：
  - 精确 pattern（`含'.'` 且 `len>=6`，如 `'000001.SZ'`）→ 从 DB 读 snapshot 立即返回 + `has_wildcard=false`
  - 宽泛 pattern（`'SZ'`/`'SH'`/`'000001'`/`''`）→ `snapshots={}` + `has_wildcard=true`，后续 tick 通过子串匹配自动推送
- **倒排匹配**：tick 推送时遍历所有 pattern, 子串匹配命中即合并该 ws 集合
- **向后兼容**：精确 stock_code 模式（`'000001.SZ'`）仍按原 REQ-QUOTE-005 行为（订阅即收）

#### Scenario: 全市场 pattern 匹配所有 tick

- **GIVEN** 客户端订阅 `{stock_codes: [""]}`
- **WHEN** 后端收到任意 tick
- **THEN** MUST 推送给该客户端（空 pattern 永远匹配）

#### Scenario: 市场 pattern 只匹配该市场

- **GIVEN** 客户端订阅 `{stock_codes: ["SZ"]}`
- **WHEN** 后端收到 tick `stock_code=600000.SH`
- **THEN** MUST NOT 推送给该客户端
- **WHEN** 后端收到 tick `stock_code=000001.SZ`
- **THEN** MUST 推送给该客户端

#### Scenario: pattern 化后 subscribe_ack 行为分流

- **GIVEN** 客户端订阅 `{stock_codes: ["000001.SZ", "SZ", ""]}`
- **THEN** subscribe_ack MUST 包含 `snapshots["000001.SZ"]`（精确部分）
- **AND** MUST 设置 `has_wildcard=true`（有宽泛 pattern）
- **AND** 后续 tick 推送中所有这三个 pattern 都生效

### REQ-QUOTE-007: 前端 auto-sub 全市场订阅阈值（holdings-auto-sub-batch 2026-08-10）

持仓自动订阅（`holdings_bootstrap._syncQuoteSubs`）MUST 在持仓代码数 > 100 时切 `''` 全市场订阅一次：

- 触发条件：holdings 的 positions 代码**去重后数量 > 100**
- 行为：调 `quote.subscribe(全量 codes)` 一次（`quote.js` 内部 `>100` 转 `['']` 全市场），并置 `_fullMarketSubscribed=true`
- 已全市场订阅后，后续 WS `pos_push` 不再逐只增量订阅，也不逐条刷日志
- 持仓缩回 **≤100** → 退出全市场模式，恢复逐只增量订阅
- 阈值 `100` 与 `quote.js subscribe()` 既有 `>100 转 ''` 约定一致

#### Scenario: 持仓洪峰只订阅一次

- **GIVEN** 前端持仓 2197 只（>100）
- **WHEN** broker 重连后 WS pos_push 洪峰逐条到达
- **THEN** `_syncQuoteSubs` 首次见 codeSet>100 时 MUST 调一次 `quote.subscribe(全量 codes)`（后端收 `''` 全市场 pattern）
- **AND** 后续每条 push MUST NOT 再发订阅 / 不刷「持仓订阅增量」日志

#### Scenario: 持仓缩回阈值以下恢复增量

- **WHEN** 持仓从 2197 只降到 ≤100
- **THEN** MUST 退出全市场模式
- **AND** 后续新持仓按逐只增量订阅

## Scenarios

### S-QUOTE-001: 正常行情推送

Given hqserver 已启动，RabbitMQ 行情队列有数据  
When QMT 推一条 `600030.SH|...|12.34|...`  
Then WS 客户端收到 `{"type":"quote","channel":"quote_update","data":{"stock_code":"600030.SH","last_price":12.34,"fields":[...],"body":"..."}}`

### S-QUOTE-002: 缓冲区满导致背压

Given `MAX_QUEUE_SIZE=5` 且 4 worker 全部被某慢任务卡住  
When RabbitMQ 推第 6 条  
Then `_consume` 协程的 `await task_queue.put(...)` 阻塞，RabbitMQ 端停止 ACK，下游被背压

### S-QUOTE-003: GBK 解码失败

When body 字节是合法 UTF-8 但非 GBK  
Then `stock_code` 用 UTF-8 解码，前端仍能收到（字段里替换坏字节）

### S-QUOTE-004: WS 客户端断开

Given 一个 WS 客户端连接  
When 它断网  
Then `send` 抛异常，连接被加入 `dead` 集合，函数结束前从 `_ws_clients` 移除

## Data Flow

```
RabbitMQ quota.exchange (FANOUT, durable=False)
        ↓ aio_pika iterator (no_ack=False)
asyncio.Queue (maxsize=5000)
        ↓ 4 workers
   (a) quota.broadcast.exchange (Topic, durable=True) ─── 兼容旧订阅
   (b) WebSocket :8765 ─── 前端直连
```

## Known Issues (from analysis)

- 🟢 hqserver 已有 18 个 mock-based 单元测试，**18/18 全绿**
- 🟡 `probe_hqserver.py` 临时探针脚本已删；如果需要可加进 `scripts/`
- 🟡 没有 reconnect-on-disconnect 的统一封装，靠 `aio_pika.connect_robust` 自带
