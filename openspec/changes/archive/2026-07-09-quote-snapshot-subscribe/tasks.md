# Tasks

## 1. OpenSpec 工件
- [x] 1.1 proposal.md
- [x] 1.2 spec-deltas/data-model.md
- [x] 1.3 spec-deltas/backend-ws.md
- [x] 1.4 spec-deltas/frontend.md
- [x] 1.5 tasks.md

## 2. 后端: QuoteSnapshotRepo
- [ ] 2.1 `server/repo/quote_snapshots.py` — 实现 `upsert/get_latest/get_latest_multi`
- [ ] 2.2 `server/repo/__init__.py` re-export

## 3. 后端: quote_consumer 全字段解析 + 写入
- [ ] 3.1 `quote_consumer.py:_parse_tick` 改写 — 解析 hqserver fields[0..28] → 23 字段 dict
- [ ] 3.2 `quote_consumer.py:_save_snapshot` 新增 — 调 repo.upsert, 不抛错
- [ ] 3.3 `quote_consumer.py:_fanout_tick` 改 broadcast → broadcast_to_subscribers
- [ ] 3.4 (可选) 失败日志加调试信息

## 4. 后端: WSManager 订阅 registry
- [ ] 4.1 `server/ws/manager.py` 加 `subscriptions`/`subscribers` dict
- [ ] 4.2 add_subscription / remove_subscription / cleanup_ws
- [ ] 4.3 broadcast_to_subscribers(stock_code, message, exclude_ws=None)
- [ ] 4.4 broadcast (fallback 老前端) 保持不变

## 5. 后端: ws endpoint 处理 subscribe
- [ ] 5.1 `ws/endpoint.py:websocket_endpoint` 收消息循环增加 `subscribe`/`unsubscribe` 分支
- [ ] 5.2 同步查询 snapshot → ws.send 多条 snapshot 帧
- [ ] 5.3 推 subscribe_ack
- [ ] 5.4 ws disconnect 调 cleanup_ws

## 6. 前端: quote store 订阅接口
- [ ] 6.1 `quote.js` 加 subscribe/unsubscribe 函数
- [ ] 6.2 pending_subscriptions Set (幂等)
- [ ] 6.3 onWsOpen 队列 flush

## 7. 前端: ws_dispatch 扩展
- [ ] 7.1 `ws_dispatch.js:dispatchPayload` 加 snapshot/subscribe_ack 分支
- [ ] 7.2 snapshot → quoteStore.update; subscribe_ack → pending remove

## 8. 前端: Holdings.vue 订阅
- [ ] 8.1 加载持仓后批量订阅
- [ ] 8.2 watch listings 增量 diff 订阅新增

## 9. 前端: Trade.vue 订阅
- [ ] 9.1 OrderForm watch form.stock_code, debounce 300ms 调 subscribe([code])
- [ ] 9.2 OrderForm mount 时若 default 有值立即 subscribe

## 10. 前端: QuotePanel.vue 订阅
- [ ] 10.1 mount 时订阅 props.stock_code

## 11. 验证 + spec 同步 + archive + commit
- [ ] 11.1 backend 重启看 quote_consumer.ticks_total 仍累计
- [ ] 11.2 模拟前端 ws 发 subscribe → backend 推 snapshot 帧
- [ ] 11.3 QuoteSnapshot 表 confirm 有持久化数据
- [ ] 11.4 git commit `feat(server,client): QuoteSnapshot 写入 + ws subscribe 协议 + 前端持仓/下单订阅`
- [ ] 11.5 openspec archive
- [ ] 11.6 第二个 commit 同步 spec 到 openspec/specs/

## 12. 【2026-07-09 插入】hqserver 修复前置
QMT publisher 改用 `\n` 合并多条 tick 为单 RabbitMQ 消息，hqserver 必须按行拆解否则下游全错位。

- [x] 12.1 `hq/hqserver.py:quota_worker` 入 body 后先 `split(b"\n")`, 每条 tick 单独 publish (routing_key=stock_code) + 单独 WebSocket 帧
- [x] 12.2 加 `HQ_DEBUG` env var (1/true/yes/on), 启动 debug 模式每 tick 日志一行
- [x] 12.3 验证: 重启 hqserver, `/tmp/probe_hq_full.py` 取 1 帧,确认 fields=31,字段索引 [0..30] 与 qmt_publisher.py:format_quote 一致
- [ ] 12.4 确认: 旧前端 quote.js 注释(30 字段,[9..13] 卖1..5)有误,真实是 31 字段,卖1..5 在 [11..15],本次前端一并修正

## 字段索引最终确认 (2026-07-09 真实测试 603162.SH)

```
[ 0] stock_code           '603162.SH'
[ 1] datetime             '20260709103032.197'
[ 2] 最新价                '9.23'
[ 3] 开盘价                '9'
[ 4] 最高价                '9.54'
[ 5] 最低价                '8.73'
[ 6] 昨收                  '9.18'
[ 7] 成交量                '294089'
[ 8] 成交额                '270019200'
[ 9] openInt              '13'         ← QMT 全推特有, ORM 无对应字段, parse 跳过
[10] transactionNum       '0'          ← QMT 全推特有, ORM 无对应字段, parse 跳过
[11..15] askPrice1..5      '9.23' '9.24' '9.25' '9.26' '9.27'
[16..20] bidPrice1..5      '9.21' '9.20' '9.19' '9.18' '9.17'
[21..25] askVol1..5         '32' '367' '12' '469' '14'
[26..30] bidVol1..5         '29' '213' '40' '8' '20'
```

askPrice 卖价方向（最低到最高）, bidPrice 买价方向（最高到最低）。对应 QMT `q.get("askPrice", [...])` / `q.get("bidPrice", [...])`。

⚠️ 之前 `client/src/stores/quote.js` 注释把 `[9..13]` 当卖1..5价是错的,真实是 `[11..15]`,本次前端一并修正(Step 6)。
