# Quote 行情落地 + 按标的订阅协议

## Why

现状（EvTrade v20）的行情流只有 push，没有持久化、没有订阅协议：

1. `quote_snapshots` 表 23 个字段已建，无任何代码写入，仅 `quote_consumer._load_prev_close` 单读 prev_close 一个字段
2. `quote_consumer._parse_tick` 只解 `stock_code + last_price` 两个字段，5 档买卖价量 / OHLC / volume / amount 全丢
3. 前端 ws_heartbeat 的 `quote_update` channel 是 **broadcast 全市场** —— 不分标的，每个 ws 客户端都收全场 tick（HFT 秒级几百 tick/连接 ×200 连接 ≈ 50KB/s/连接）
4. 持仓页 / Trade.vue 打开时不会从表中拉快照，单纯等 push，第一次喂入延迟 0~16s 不等
5. 用户在 Trade.vue 输入代码 → OrderForm 没触发任何行情请求，等 push 推送
6. **【2026-07-09 重要】QMT publisher 改用 `\n` 合并多条 tick 为一条 RabbitMQ 消息发送（`scripts/qmt_publisher.py:on_quote` + `format_quote`），但当前 `hq/hqserver.py:quota_worker` 只用 `body_text.split("|")` 解析整条 body，导致后续 quote_consumer 全字段解析全部错位** —— 必须先在 hqserver 拆 `\n` 为多 tick，逐行 broadcast；否则下游订阅/snapshot 写入均失效

用户需求（2026-07-09 9:30 chat）：

- 增加行情表，记录证券代码 + 全部行情要素 + ts，持续刷新
- 前端按标的订阅：持仓的每个标的逐条订阅；下单页输入代码时订阅
- 订阅成功立刻从行情表返当前最新，后续通过订阅推送变化快照

## What Changes

### 1. quote_snapshots 表落地写入

- `server/services/strategy/quote_consumer.py:_parse_tick` 改为解析 hqserver fields 全部 23 字段
- `server/services/strategy/quote_consumer.py` 新增 `_save_snapshot(db, parsed)` — `INSERT ... ON CONFLICT (stock_code) DO UPDATE SET ...`（latest-only 模式）
- `server/repo/quote_snapshots.py` 从占位升级为完整 CRUD:
  - `upsert(db, snapshot_data)`
  - `get_latest(db, stock_code)`
  - `get_latest_multi(db, stock_codes)` — 一次性批量查

### 2. ws subscribe 协议（前后端联动）

**协议消息**(ws JSON):

- Client → Server:
  - `{type:"subscribe", stock_codes:["000001.SZ","600030.SH"]}` — 批量订阅多个
  - `{type:"unsubscribe", stock_codes:["..."]}` — 批量退订
- Server → Client:
  - `{type:"snapshot", stock_code:"...", data:{...23 字段 + ts}, ts:...}` — 订阅成功的当前最新快照（一条一条推送，多标的多条）
  - `{type:"quote", channel:"quote_update", data:{...}}` — 增量 tick（同 v20 形式，仅推给订阅了此标的的 ws）
  - `{type:"subscribe_ack", stock_codes:[...], count:N}` — 订阅响应确认

**实现**(后端):

- `server/ws/manager.py` 加 `subscriptions: Dict[WebSocket, Set[str]]` + `subscribers: Dict[str, Set[WebSocket]]` (倒排索引)
- 新增 `add_subscription(ws, stock_code)` / `remove_subscription(ws, stock_code)` / `broadcast_to_subscribers(stock_code, msg, exclude_ws=None)`
- `server/ws/endpoint.py:websocket_endpoint` 改为处理 `subscribe` / `unsubscribe` 消息（不只是心跳）:
  1. ws connect → 自动 register this conn
  2. 收 `subscribe` → 同步: (a) 加 registry, (b) 批量 `repo.quote_snapshots.get_latest_multi()` → 推多条 `snapshot` 帧, (c) 推 `subscribe_ack`
  3. 收 `unsubscribe` → 移 registry
  4. 收 `ping` → 回 `pong` (v10 兼容)
- `server/services/strategy/quote_consumer.py:_fanout_tick` 改 `ws_manager.broadcast` → `ws_manager.broadcast_to_subscribers(stock_code, ...)`：未订阅则 0 流量

**实现**(前端):

- `client/src/stores/quote.js` 加 `subscribe(stock_codes)` / `unsubscribe(stock_codes)` 方法（内部 ws.send）
- `client/src/stores/quote.js` 处理 `snapshot` 消息（合并到 byCode）
- `client/src/stores/ws_dispatch.js` 加 `dispatchPayload` 分支:`snapshot` / `subscribe_ack`
- `client/src/views/Holdings.vue` 在 holdings load 后批量 `quoteStore.subscribe(holdings.map(h=>h.code))`
- `client/src/views/Trade.vue:OrderForm` watch `form.stock_code` — 防抖 300ms → `quoteStore.subscribe([code])`
- `client/src/components/QuotePanel.vue` 打开时订阅（按 props.stock_code）

### 3. NOT CHANGED

- Quote/Order/Strategy REST API 不动
- broker (xtquant) 不动
- RabbitMQ 拓扑不动 (hqserver 仍 FANOUT broadcast)
- 现有 quote store 的 `update()` 接口保持兼容（新协议走同一接口）

## Impact

- **能力**: 后端 repo=新实现,后端 ws=扩协议,前端 store+vue=扩订阅接口
- **范围**: 5 个后端文件 + 3 个前端文件 + 2 个 spec 文件 + 1 个 proposal/tasks
- **API**: ws JSON 协议扩展（新 type，旧 type 兼容）
- **DB**: quote_snapshots 表加 upsert path（latest-only，不增加行数）
- **性能**:
  - 服务端每 tick DB upsert ~6/s × 23 字段 = 简单 SQL，单连接 ok
  - ws 流量从 broadcast (全场) → 按订阅 (持仓 ~10-30 个) → **降流量 95%**
  - ws subscribe_resp 时一次最多推 30 个 snapshot = 无压力
- **风险**: 中
  - ws 协议变:旧 ws_heartbeat 不发 subscribe 也能继续收（兼容性保留 broadcast 模式 for fallback 时长 5s 兼容老前端）
  - sql 写入失败兜底:log.error 不抛出（不阻塞 tick flow）
  - ws.subscribe 时标的在表里无快照 → `snapshot` 帧省略,`subscribe_ack` 仍返。前端先空白等 push

## Alternatives Considered

- **方案 A（已采用）**: 按标的单条 subscribe_ack + 单条 snapshot 帧
  - Pros: 协议简单，前端处理一条条 toMap
  - Cons: 帧数 = 标的数（最多 30 个/批 ok）
- **方案 B（弃）**: 一次性返回 `snapshots: {stock_code: {...}}` 对象
  - Pros: 单帧
  - Cons: 客户端流式处理麻烦，json 大，O(N) 反序列化
- **方案 C（弃）**: 用 REST 单独拉快照 `/api/quote/snapshots?codes=...`
  - Pros: 协议复用
  - Cons: 多一路连接 (REST + WS)，ws subscribe ack 已是实时，无需 REST

## Tasks

- [ ] 1. proposal/spec/tasks 三件套完成
- [ ] 2. 后端: `repo/quote_snapshots.py` upsert/get_latest/get_latest_multi
- [ ] 3. 后端: `quote_consumer.py` 全字段 parse + _save_snapshot 调 repo.upsert
- [ ] 4. 后端: `ws/manager.py` 加 subscriptions 倒排索引 + broadcast_to_subscribers
- [ ] 5. 后端: `ws/endpoint.py` 处理 subscribe/unsubscribe 消息 + ack + snapshot 帧
- [ ] 6. 前端: `quote.js` 加 subscribe/unsubscribe 方法 + snapshot 帧处理
- [ ] 7. 前端: `ws_dispatch.js` dispatch snapshot 类型
- [ ] 8. 前端: `views/Holdings.vue` 批量订阅持仓标的
- [ ] 9. 前端: `views/Trade.vue` watch form.stock_code 防抖订阅
- [ ] 10. 前端: `components/QuotePanel.vue` mount 时订阅 props.stock_code
- [ ] 11. spec 同步 + archive + commit + push

## 相关

- hqserver `hq/hqserver.py:155-159` 已生成 30 字段 line `body_text = raw_body.decode("gbk", errors="replace")` + `fields = body_text.split("|")` — 字段对应前 30 位的行情
- QuoteSnapshot ORM `server/models/orm.py:295-334` 23 字段已就绪
- 现有 ws_dispatch `_onQuote` 走 `quoteStore.update()` — 直接复用
