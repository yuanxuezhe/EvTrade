# hqserver 行情服务说明

## 对应代码路径

- `e:/EvTrade/hq/hqserver.py`（行情并发消费 + WebSocket 直推路由器，约 320 行）
- `e:/EvTrade/hq/hqsuber.py`（下游按标的订阅客户端示例）
- 配置来源：`e:/EvTrade/server/.env`（与 EvTrade 主服务共享同一 .env）

## 功能概述

hqserver 是 EvTrade 的**独立行情推送进程**（单文件 asyncio 程序，WS 监听 :8765）：消费 RabbitMQ 基础行情队列 `EvQuota`（上游 QMT publisher 经 `quota.exchange` FANOUT 发布的批量 tick），经内部 `asyncio.Queue` 缓冲与固定 worker 池拆分后，把每条 tick 以 JSON 帧 `{"type":"quote", ...}` 广播给**所有**已连接的 WebSocket 客户端（前端行情页 + strategy_exec 实盘 LiveRunner）。

架构（hqserver.py 头部注释）：

```
RabbitMQ quota.exchange (FANOUT, durable=False)
      ↓ aio_pika iterator + 显式 ACK（安全极速接收）
asyncio.Queue 内部缓冲 (maxsize=5000, 天然背压)
      ↓ NUM_WORKERS 个固定 worker 协程（CPU 受控）
(a) [已删] quota.broadcast.exchange 重发 —— 2026-07-10 移除（无 binding, 99.3% 丢弃）
(b) 内置 WebSocket 服务 :8765 —— 前端直连
```

## 文件清单

| 代码文件 | 作用 |
|----------|------|
| `hqserver.py` | 主服务：RabbitMQ 消费 + worker 池 + WS 广播 + 看门狗 + 优雅关闭 |
| `hqsuber.py` | 示例订阅客户端：绑 `quota.broadcast.exchange`（TOPIC）按 stock_code/routing_key 订阅（该交换机现无发布方，仅留作示例/回滚参考） |

## 核心实现

### 启动与配置（HQ_* 环境变量）

hqserver 用 `dotenv` 加载 `../server/.env`（`override=False`，与 server/config.py 共享一处维护）；`_env/_env_int/_env_bool` 三个助手读环境变量：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `HQ_RABBITMQ_URL` | `amqp://192.168.10.2:5672/` | RabbitMQ 地址 |
| `HQ_EXCHANGE_NAME` | `quota.exchange` | 上游 FANOUT 交换机（durable=False，对齐服务器现存属性） |
| `HQ_SOURCE_QUEUE` | `EvQuota` | 上游基础行情队列（durable=True） |
| `HQ_BROADCAST_EXCHANGE` | `quota.broadcast.exchange` | **DEPRECATED 2026-07-10**：无 binding 时 99.3% 消息丢弃，重发逻辑已删，变量仅保留以备回滚 |
| `HQ_NUM_WORKERS` | `4` | worker 协程数（防吃满单核 CPU） |
| `HQ_MAX_QUEUE_SIZE` | `5000` | 内部缓冲上限（满则背压阻塞） |
| `HQ_PREFETCH_COUNT` | `16` | aio-pika 预取数（保持 NUM_WORKERS×4 量级） |
| `HQ_DEBUG` | `False` | 每个 tick 打一行日志（生产必须关，量级数千/秒） |
| `HQ_WS_HOST` | `0.0.0.0` | WS 监听地址 |
| `HQ_WS_PORT` | `8765` | WS 监听端口（`ws://<host>:8765`） |

启动：`python hq/hqserver.py`（`loop.run_until_complete(main())`，Ctrl+C 优雅退出）。

### RabbitMQ 消费（_consume）

- `declare_queue("EvQuota", durable=True, exclusive=False)` + `declare_exchange("quota.exchange", FANOUT, durable=False)` + `bind(routing_key="")`。
- `source_queue.iterator(no_ack=False)` 显式确认：消息体先 `await task_queue.put(message.body)` 入本地缓冲（缓冲满自动背压阻塞），成功后再 `message.ack()` 释放 —— 崩溃时未 ACK 消息可被 RabbitMQ 重投。

### worker 池（quota_worker，2026-07-09 quote-batch-split）

QMT publisher（`scripts/qmt_publisher.py:on_quote`）把多条 tick 用 `\n` 合并为**单条** RabbitMQ 消息发送。worker 处理：

1. `raw_body.split(b"\n")` 拆回逐行 tick。
2. 每行按 `|` 切首字段，`gbk`（失败退化 utf-8）解码出 `stock_code`。
3. 组装 WS 帧并 `_broadcast_ws`：

```json
{
  "type": "quote",
  "channel": "quote_update",
  "data": {
    "stock_code": "600519.SH",
    "last_price": 1700.5,          // fields[2] 解析, 失败为 null
    "fields": ["600519.SH", "...", "1700.5", ...],   // 全字段数组 (gbk 文本 split "|")
    "body": "600519.SH|...|1700.5|..."               // 原始行文本
  }
}
```

4. `HQ_DEBUG=1` 时打印 `[TICK]` 一行（fields 截断到 31 个防日志爆炸）。
5. `finally: task_queue.task_done(); await asyncio.sleep(0)` —— 强制让出 CPU，防密集计算阻塞网络 I/O 导致心跳断开。

注意：strategy_exec 的 LiveRunner 实际消费的 tick 结构 `{stime, lastPrice, open, high, low, volume}` 与此处的 `fields/body` 原始格式不同 —— LiveRunner `_on_tick` 里做了字段适配/兜底（live.py `_connect_and_consume` 过滤 `data.code`/`data.stock_code` 匹配后传入聚合器，聚合器对缺失字段用 `tick.get(...)` 容错）。

### WebSocket 服务（:8765）

- `websockets.serve(_ws_handler, WS_HOST, WS_PORT, ping_interval=15, ping_timeout=60)`（2026-07-09 fix：默认 20/20 在 tick 短暂停顿时被误判断连 1011）。
- 客户端集合 `_ws_clients: Set` + asyncio.Lock；`_register_ws/_unregister_ws` 记日志（含当前连接数）。
- `_broadcast_ws(payload)`：快照 clients 列表后逐个 `await c.send(json.dumps(payload))`；失败的放入 dead 集合统一摘除，个别失败不影响整体。
- `_ws_handler`：websockets>=11 兼容（handler 只收 `(websocket,)` 单参）；客户端不发消息，`async for _ in websocket` 仅为检测断开（keepalive）。
- **无订阅过滤**：服务端把所有 tick 推给所有连接（FANOUT 语义）；按标的过滤由客户端自己做（如 LiveRunner 只处理自己 stock_code 的帧）。订阅消息 `{"type":"subscribe","stock_codes":[...]}` 发送无害但服务端不解析。

### 看门狗与优雅关闭

- `_consume` 任务 `add_done_callback(handle_consume_result)`：消费协程异常崩溃 → `log.critical` + `stop_event.set()` 强制终止主程序，防假死。
- SIGINT/SIGTERM（Windows 下 add_signal_handler NotImplemented 则跳过）→ `stop_event.wait()` 返回 → 依次 cancel consume/workers、`ws_server.close()`、关 channel/connection。

### hqsuber.py（示例订阅端）

演示下游程序按标的订阅的写法：`declare_exchange("quota.broadcast.exchange", TOPIC, durable=True)` → 声明 `exclusive=True` 临时队列（程序退出自动销毁）→ 按 `SUBSCRIBE_STOCKS`（支持 `*.SH` 通配）逐个 bind → iterator 消费，`message.routing_key` 即标的，body 为 gbk 文本。**注意**：hqserver 2026-07-10 已删除向该交换机重发的逻辑，hqsuber 目前收不到数据，仅作协议示例 / 回滚参考保留。

### 与 server/.env 共享配置

hqserver 不自带 .env，直接 `load_dotenv("../server/.env")`，保证 RabbitMQ 地址等与 EvTrade 主服务一处维护。strategy_exec 侧连 hqserver 用自己的 `HQ_WS_URL`（默认 `ws://127.0.0.1:8765/quota.broadcast`，路径部分服务端不校验）。

## 依赖关系

- 上游：RabbitMQ `quota.exchange`（QMT publisher `scripts/qmt_publisher.py` 批量发布 tick）。
- 下游：所有连 `ws://<host>:8765` 的客户端 —— 前端行情页、strategy_exec LiveRunner（实盘 tick）、其他调试工具。
- 同级：与 EvTrade server 共享 `server/.env`；与 strategy_exec 通过 WS 解耦（无代码依赖）。

## 修改指南

- 加按标的订阅/退订：在 `_ws_handler` 解析客户端首条 subscribe 消息并维护 `conn -> set(stock_code)` 映射，`_broadcast_ws` 改为按订阅集过滤（注意向后兼容：未订阅的旧客户端保持全推）。
- 改端口/地址：`server/.env` 的 `HQ_WS_HOST`/`HQ_WS_PORT`；strategy_exec 侧同步改 `HQ_WS_URL`。
- tick 字段升级：保持 `data.fields`/`data.body` 原始字段不变前提下新增解析字段；消费端（前端 + LiveRunner `_BarAggregator`）需同步。
- 性能调优：`HQ_NUM_WORKERS`（CPU 核数上限内）、`HQ_MAX_QUEUE_SIZE`（内存换延迟）、`HQ_PREFETCH_COUNT`；调试完务必 `HQ_DEBUG=0`。
- 回滚 RabbitMQ 广播：恢复 `BROADCAST_EXCHANGE` 相关重发块（git 历史 2026-07-10 之前版本），hqsuber 即可用。
