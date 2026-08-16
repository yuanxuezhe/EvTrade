# RPC客户端

## 对应代码路径

- `server/rpc/client.py`（facade 兼容垫片，re-export 全部符号）
- `server/rpc/transport.py`（RPClient 传输骨架 + 单例生命周期）
- `server/rpc/parsers_common.py` / `parsers_business.py` / `parsers_push.py`（应答解析）
- `server/rpc/handlers.py`（业务调用入口 qry_*/ord_stk/cancel_order）
- `server/infra/mq.py`（MessageQueueClient 基类）
- `server/services/push/dispatcher.py`（push 业务编排，另见 routes.py / run_handlers.py）

## 功能概述

EvTrade 与 QMT 柜台通过 RabbitMQ + msgpacket 二进制协议通信：一个 topic exchange（msgpacket.exchange）+ 三条 durable 队列（Req/Reply/Push）。RPClient 维护长连接，call() 发请求等应答（msgid 配对 future），push listener 常驻消费柜台主动推送（ord_cfm/trd_cfm/pos_push）交 PushDispatcher 落库并广播 WS。client.py 是 phase-2 拆分后的 facade，保持旧 import 路径兼容。

## 文件清单
| 代码文件 | 作用 |
|----------|------|
| server/rpc/client.py | facade：re-export transport/parsers/handlers/push 符号（测试 monkeypatch 锚点） |
| server/rpc/transport.py | RPClient（pending futures、call 超时、msgid→order_no cache、reply/push listener）、get_rpc_client/close_rpc_client |
| server/rpc/parsers_common.py | _select_rs/_parse_code_msg/_iter_rows/_to_int/_to_float/_empty 通用解析 |
| server/rpc/parsers_business.py | _parse_asset/_parse_orders/_parse_trades/_parse_positions/_parse_order_ack |
| server/rpc/parsers_push.py | _iter_push_rows（push 行提取；旧名 _parse_push_rows alias） |
| server/rpc/handlers.py | qry_asset/qry_orders/qry_trades/qry_positions/ord_stk/cancel_order |
| server/infra/mq.py | MessageQueueClient：aio_pika connect/publish(listen_replies/listen_pushs) 骨架 |
| server/services/push/* | PushDispatcher + _PUSH_CHANNEL 路由表 + 落库/日志 helper |

## 核心实现

### 队列与协议常量（来自 config.settings）
- `RABBITMQ_URL` / `EXCHANGE_NAME=msgpacket.exchange` / `QUEUE_REQ=EvTrade.Test.Req` / `QUEUE_REPLY=EvTrade.Test.Reply` / `QUEUE_PUSH=EvTrade.Test.Push`。
- `MAX_PENDING = 100`：在途 RPC 上限，慢应答保护。
- 协议：`MsgPacket(MSG_TYPE_REQUEST, "V1.0")`；`set_func` + 可选 `set_headers`（逗号分隔字段名）+ `add_row`/`set_value`（第一行请求体）；`finalize()` 后 `encode()` 得 wire bytes。msgid 由库自动生成（UUID v4 hex 32 字符），柜台应答须回写同 msgid。
- `_clean_id(raw)`：定长 char[] 字段去 `\0` 与空白（两端必须同规则，否则 dict 查不到）；`_wire_dump(pkt)`：wire_to_string 报文 dump 排障。

### RPClient 类（继承 infra.mq.MessageQueueClient）
- `async connect()`：幂等守卫（已连接跳过）；基类声明 exchange + 三队列 + bind；构造 PushDispatcher；起 3 个协程：`_listen_replies`、`_listen_pushs`、`_msgid_cache_gc_loop`。publisher confirm 开启。
- `async call(func, timeout=None, headers=None, values=None, msgid_meta=None) -> MsgPacket`
  1. timeout 缺省取 `settings.RPC_TIMEOUT`（30s）；pending ≥ MAX_PENDING 抛 RuntimeError。
  2. 构造 MsgPacket + msgid；msgid_meta（order_no/trd_date/stock_code）注册进 `_MSGID_ORDERNO_CACHE`（v84 废单反查，TTL 60s，GC 协程 30s 周期）。
  3. 记 `[svc->rpc]` 日志（trace_id=msgid）→ `publish(wire, routing_key=QUEUE_REQ, timeout=5s confirm)`；confirm 超时清 pending/cache 抛 RuntimeError。
  4. `await asyncio.wait_for(future, timeout)` 等应答；超时清 pending + `[svc<-rpc] TIMEOUT` warning 并 re-raise。
  5. 收到后 `_log_reply` 记 `[svc<-rpc] reply func=... code=... rows=...`。
- reply listener：`_handle_reply(wire)` decode → `_clean_id(msgid)` 匹配 pending future set_result；未匹配记 warning（列出等待中的 msgid）。func=ord_stk 时额外走 `_handle_ord_stk_reply`（v91）：code=0 → 状态 48 才推进到 49"待报"（防倒退，ord_cfm 可能先到）；code≠0 → 更新为 57 废单 + 抹平 cancelled_volume；DB 写 `run_in_executor`，完成后 `_broadcast_order_cfm` 推前端（与 push 同协议 `{type:'ord_cfm',...}`）。
- push listener：decode → 取 func → 委托 `PushDispatcher.dispatch(pkt, func, mt, wire_len)`。路由表 `_PUSH_CHANNEL = {"ord_cfm": "order_update", "trd_cfm": "trade_update", "pos_push": "position_update"}`（v118 pos_push 为持仓唯一数据源；xtquant 协议无 pos_cfm/ast_cfm）。
- 单例：`get_rpc_client()` 懒建 + connect；`close_rpc_client()` 关连接置 None。main.py startup/shutdown 管理。

### handlers.py 业务入口
- `qry_asset()` → call("qry_ast") → _parse_asset → `{code,msg,list}`
- `qry_orders()` → "qry_ord"；`qry_trades()` → "qry_mch"；`qry_positions()` → "qry_pos"
- `ord_stk(stock_code, volume, price_type, price, order_type, ...)`：下单，remark 用 `settings.ORDER_REMARK`，携带 msgid_meta 供废单反查。
- `cancel_order(...)`：撤单（本地生成 order_flag=1 撤单行，user_def="CANCEL:{orig}"）。

## 依赖关系
- 上游：api/orders、services/reconcile、rpc_health（资金同步）、strategy signal_consumer（服务 token 调本地 API 后走同一链路）
- 下游：RabbitMQ（aio_pika connect_robust）、msgpacket 库、PushDispatcher → tables 落库 + ws_manager 广播

## 修改指南
- 新增柜台接口：在 handlers.py 加 `qry_xxx()`（call + 新 _parse_* 放 parsers_business.py），勿绕过 handlers 直接用 client.call。
- push 新事件类型：改 services/push/routes.py 路由表 + dispatcher handler；xtquant 协议不推的事件勿订阅。
- 队列/交换机名改动需与 broker 端同步；durable 队列需先在 RabbitMQ 清理。
- 测试 patch 锚点统一走 `rpc.client` facade（如 `patch('rpc.client.aio_pika.connect_robust')`）。
