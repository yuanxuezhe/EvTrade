#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EvQuota 行情并发消费 + WebSocket 直推路由器（高性能稳定版）

架构：
  RabbitMQ quota.exchange (FANOUT, durable=False)
        ↓ aio_pika iterator + 标准确认(ACK)     安全极速接收
  asyncio.Queue 内部缓冲区 (maxsize=5000, 天然背压)
        ↓ N 个固定 worker 协程           CPU 受控
  (a) quota.broadcast.exchange (Topic, routing_key=stock_code)  ← 兼容旧版订阅
  (b) 内置 WebSocket 服务 :8765                               ← 前端直连
"""

import asyncio
import json
import logging
import os
import signal
import sys
from typing import Set

import aio_pika
from websockets import serve
from websockets import WebSocketServerProtocol  # websockets 9.x compatible

# ==================== 配置 ====================
# 优先从 server/.env 加载（与 server/config.py 共享同一个 .env），便于一处维护。
try:
    from dotenv import load_dotenv
    _ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server", ".env")
    if os.path.exists(_ENV_PATH):
        load_dotenv(_ENV_PATH, override=False)
except ImportError:
    pass


def _env(key: str, default: str) -> str:
    v = os.environ.get(key)
    return v if v not in (None, "") else default


def _env_int(key: str, default: int) -> int:
    try:
        return int(_env(key, str(default)))
    except ValueError:
        return default


# ---- RabbitMQ ----
RABBITMQ_URL = _env("HQ_RABBITMQ_URL", "amqp://192.168.10.2:5672/")
EXCHANGE_NAME = _env("HQ_EXCHANGE_NAME", "quota.exchange")           # 上游 broker publish 入口（服务器现存为 False）
SOURCE_QUEUE = _env("HQ_SOURCE_QUEUE", "EvQuota")                    # 上游固定的基础行情队列名（服务器现存为 True）
BROADCAST_EXCHANGE = _env("HQ_BROADCAST_EXCHANGE", "quota.broadcast.exchange")  # 内部转发用

# ---- 并发与缓冲 ----
NUM_WORKERS = _env_int("HQ_NUM_WORKERS", 4)          # 严格限制并发处理的 Worker 数量，防止吃满单核 CPU
MAX_QUEUE_SIZE = _env_int("HQ_MAX_QUEUE_SIZE", 5000) # 内部缓冲区大小，防止内存暴涨
PREFETCH_COUNT = _env_int("HQ_PREFETCH_COUNT", 16)   # aio-pika 消费者单次预取消息数（保持 NUM_WORKERS*4 量级即可）

# ---- WebSocket ----
WS_HOST = _env("HQ_WS_HOST", "0.0.0.0")
WS_PORT = _env_int("HQ_WS_PORT", 8765)               # 前端直连端口：ws://<host>:8765

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("hqserver")

# ==================== WebSocket 客户端集合 ====================
_ws_clients: Set[WebSocketServerProtocol] = set()
_ws_clients_lock = asyncio.Lock()


async def _register_ws(conn: WebSocketServerProtocol):
    async with _ws_clients_lock:
        _ws_clients.add(conn)
    log.info(f"[WS] 客户端已连接: {conn.remote_address}, 当前总连接数={len(_ws_clients)}")


async def _unregister_ws(conn: WebSocketServerProtocol):
    async with _ws_clients_lock:
        _ws_clients.discard(conn)
    log.info(f"[WS] 客户端已断开: {conn.remote_address}, 当前总连接数={len(_ws_clients)}")


async def _broadcast_ws(payload: dict):
    """把行情推给所有 WS 客户端；个别失败不影响整体。"""
    if not _ws_clients:
        return
    msg = json.dumps(payload, ensure_ascii=False)
    dead: Set[WebSocketServerProtocol] = set()
    
    async with _ws_clients_lock:
        clients = list(_ws_clients)
    
    for c in clients:
        try:
            await c.send(msg)
        except Exception:
            dead.add(c)
            
    if dead:
        async with _ws_clients_lock:
            for c in dead:
                _ws_clients.discard(c)


async def _ws_handler(websocket: WebSocketServerProtocol, path: str):
    """每个 WS 连接一个 task。客户端不发消息，仅 keepalive。"""
    await _register_ws(websocket)
    try:
        async for _ in websocket:  # 只为检测断开
            pass
    finally:
        await _unregister_ws(websocket)


# ==================== Worker ====================
task_queue: asyncio.Queue = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)


async def quota_worker(worker_id: int, broadcast_exchange: aio_pika.Exchange) -> None:
    """固定的 Worker 协程，从内部队列取任务处理。"""
    publish_func = broadcast_exchange.publish

    while True:
        raw_body = await task_queue.get()
        try:
            # 字节层切 stock_code
            stock_code_bytes = raw_body.split(b"|", 1)[0]
            try:
                stock_code = stock_code_bytes.decode("gbk")
            except Exception:
                stock_code = stock_code_bytes.decode("utf-8", errors="replace")

            # ---- (a) RabbitMQ 广播（兼容旧版 Topic）----
            await publish_func(
                aio_pika.Message(body=raw_body, delivery_mode=1),
                routing_key=stock_code,
            )

            # ---- (b) WebSocket 直推（前端）----
            try:
                body_text = raw_body.decode("gbk", errors="replace")
            except Exception:
                body_text = raw_body.decode("utf-8", errors="replace")
            
            fields = body_text.split("|")
            last_price = None
            if len(fields) >= 3:
                try:
                    last_price = float(fields[2])
                except (ValueError, TypeError):
                    pass
                    
            ws_payload = {
                "type": "quote",
                "channel": "quote_update",
                "data": {
                    "stock_code": stock_code,
                    "last_price": last_price,
                    "fields": fields,
                    "body": body_text,
                },
            }
            await _broadcast_ws(ws_payload)

        except Exception as e:
            log.exception(f"[Worker-{worker_id} 错误]: {e}")
        finally:
            task_queue.task_done()
            # 强制强制让出 CPU，防止密集计算阻塞网络 I/O 导致心跳断开
            await asyncio.sleep(0)


# ==================== Main ====================
async def main() -> None:
    log.info(f"正在连接 RabbitMQ: {RABBITMQ_URL}")
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    channel = await connection.channel()

    # 【重要优化：对齐服务器现存属性】
    # 1. 声明基础行情队列（durable=True）
    source_queue = await channel.declare_queue(SOURCE_QUEUE, durable=True, exclusive=False)
    
    # 2. 声明上游交换机（durable=False）
    source_exchange = await channel.declare_exchange(
        EXCHANGE_NAME, type=aio_pika.ExchangeType.FANOUT, durable=False
    )
    
    # 3. 绑定队列到交换机
    await source_queue.bind(source_exchange, routing_key="")
    log.info(f"成功绑定上游交换机 {EXCHANGE_NAME!r}(Durable:False) 到基础行情队列 {SOURCE_QUEUE!r}(Durable:True)")

    # 4. 声明下游 Topic 广播交换机
    broadcast_exchange = await channel.declare_exchange(
        BROADCAST_EXCHANGE, type=aio_pika.ExchangeType.TOPIC, durable=True
    )
    log.info(f"已建立下游 Topic 广播交换机: {BROADCAST_EXCHANGE!r}")

    # ---- 启动 worker 池 ----
    workers = [
        asyncio.ensure_future(quota_worker(i, broadcast_exchange))
        for i in range(NUM_WORKERS)
    ]
    log.info(f"已启动 {NUM_WORKERS} 个并发处理 worker，内部缓冲区最大限制={MAX_QUEUE_SIZE}")

    # ---- 启动 WebSocket 服务 ----
    ws_server = await serve(_ws_handler, WS_HOST, WS_PORT)
    log.info(f"WebSocket 服务已成功监听: ws://{WS_HOST}:{WS_PORT}")

    # ---- 注册信号处理 ----
    stop_event = asyncio.Event()
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass  # 兼容 Windows 环境

    # ---- 启动核心消费任务并加入看门狗监听 ----
    consume_task = asyncio.ensure_future(_consume(source_queue, stop_event))
    
    def handle_consume_result(task: asyncio.Task):
        """核心消费协程看门狗：如果异常退出，强制终止主程序，防止假死"""
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.critical(f"[致命错误] 队列消费协程异常崩溃! 错误原因: {e}", exc_info=True)
            stop_event.set()

    consume_task.add_done_callback(handle_consume_result)
    log.info("行情监听看门狗已启动，开始接收数据...")

    # ---- 进入主等待循环 ----
    try:
        await stop_event.wait()
    finally:
        log.info("收到停止信号，正在优雅关闭服务...")
        stop_event.set()
        consume_task.cancel()
        for w in workers:
            w.cancel()
        ws_server.close()
        await ws_server.wait_closed()
        try:
            await channel.close()
            await connection.close()
        except Exception:
            pass
        log.info("hqserver 已安全安全退出。")


async def _consume(source_queue: aio_pika.Queue, stop_event: asyncio.Event):
    """从 RabbitMQ 队列拉取数据的核心循环"""
    # 将 no_ack 改为 False，配合 message.ack() 实现安全的显式确认机制
    async with source_queue.iterator(no_ack=False) as queue_iter:
        async for message in queue_iter:
            if stop_event.is_set():
                break
            
            if message.body:
                # 压入内部 asyncio.Queue 缓冲区，若缓冲区满了会天然产生背压(Block住)
                await task_queue.put(message.body)
                # 成功存入本地缓冲区后，安全地向 RabbitMQ 发送 ACK 释放资源
                await message.ack()


if __name__ == "__main__":
    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        log.info("程序被用户手动终止。")
        sys.exit(0)