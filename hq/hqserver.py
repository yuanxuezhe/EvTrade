#!/usr/bin/env python3
"""
EvQuota 行情并发消费与精准分发路由器 (固定协程池防打满版)

架构：
  RabbitMQ EvQuota 队列 (上游 broker 推所有 A 股行情)
        ↓ aio_pika iterator + no_ack=True   极速接收
  asyncio.Queue 内部缓冲区 (maxsize=5000, 天然背压)
        ↓ N 个固定 worker 协程            CPU 受控
  quota.broadcast.exchange (Topic, routing_key=stock_code)
        ↓
  前端 WebSocket / server.quote.subscriber (FANOUT 模式通配 *.SH / *.SZ)

关键改进（相对旧版）：
  1. 固定 4 个 worker 协程池，不为每条消息 spawn 协程
  2. 内部 asyncio.Queue 缓冲区提供天然 backpressure
  3. no_ack=True：高频场景下避免 ack 风暴
  4. Message 模板预创建：worker 内只换 body 引用
  5. 字节层切 stock_code：不 decode 整条 body
  6. asyncio.sleep(0) 让出 CPU
"""

import asyncio
import aio_pika

# ==================== 配置 ====================
RABBITMQ_URL = "amqp://192.168.10.2:5672/"
# 上游 broker 直接 publish 到 quota.exchange (Topic, durable=false)
# hqserver 创建一个 exclusive 临时队列 bind 到该 exchange, 通配 *.SH / *.SZ 收所有 A 股行情
EXCHANGE_NAME = "quota.exchange"
# 仍然保留对 EvQuota 队列的兼容（如果 broker 改回走队列模式，不至于断流）
SOURCE_QUEUE = "EvQuota"

NUM_WORKERS = 4          # 严格限制并发处理的 Worker 数量，防止吃满单核 CPU
MAX_QUEUE_SIZE = 5000    # 内部缓冲区大小，防止内存暴涨
PREFETCH_COUNT = 32      # aio_pika 一次最多预取的未确认消息数（应 >= NUM_WORKERS）

# 初始化内部异步队列
task_queue: asyncio.Queue = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)


async def quota_worker(worker_id: int, exchange: aio_pika.Exchange) -> None:
    """固定的 Worker 协程，从内部队列取任务处理"""
    # 预先创建消息模板（只复用 bytes body），避免循环内重复实例化的开销
    forward_msg = aio_pika.Message(body=b"", delivery_mode=1)
    publish_func = exchange.publish

    while True:
        # 从队列获取原生 bytes 数据
        raw_body = await task_queue.get()
        try:
            # 仅在字节流层面切出股票代码，不 decode 整条 body，降低 CPU 开销
            stock_code_bytes = raw_body.split(b'|', 1)[0]
            stock_code = stock_code_bytes.decode('gbk')

            # 复用 Message 模板：只换 body 引用
            forward_msg.body = raw_body
            await publish_func(forward_msg, routing_key=stock_code)

        except Exception as e:
            print(f"[Worker-{worker_id} Error]: {e}", flush=True)
        finally:
            task_queue.task_done()
            # 主动让出微小的 CPU 时间片，给其他异步任务执行的机会
            await asyncio.sleep(0)


async def main() -> None:
    print(f"[Router] 正在连接 RabbitMQ: {RABBITMQ_URL}...", flush=True)
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    channel = await connection.channel()

    # 通道级 QoS：限制 aio_pika 一次预取的未确认消息数
    # no_ack=True 时 aio_pika 不等待 broker confirm，但仍会受此限制影响拉取速度
    await channel.set_qos(prefetch_count=PREFETCH_COUNT)

    # 订阅上游 broker 的 quota.exchange (Topic, durable=false)
    # - passive=True：不创建只校验（broker 端已存在，durable=false 不能改）
    # - exclusive 临时队列：连接断即销毁，不留垃圾
    # - bind *.SH / *.SZ：通配所有 A 股
    source_queue = await channel.declare_queue(exclusive=True)
    source_exchange = await channel.declare_exchange(
        EXCHANGE_NAME,
        type=aio_pika.ExchangeType.TOPIC,
        durable=False,
        passive=True,
    )
    for pat in ("*.SH", "*.SZ"):
        await source_queue.bind(source_exchange, routing_key=pat)
    print(f"[Router] 已绑定 {EXCHANGE_NAME!r} (*.SH / *.SZ) 临时队列", flush=True)

    # 内部转发用的广播 Topic 交换机：routing_key=stock_code
    # broker 端已存在 quota.broadcast.exchange (durable=true)，直接 reuse
    broadcast_exchange = await channel.declare_exchange(
        "quota.broadcast.exchange",
        type=aio_pika.ExchangeType.TOPIC,
        durable=True,
        passive=True,
    )
    print("[Router] 已连接到 quota.broadcast.exchange (broker 共享, 内部转发用)", flush=True)

    # 1. 启动固定数量的后台消费工人
    workers = []
    for i in range(NUM_WORKERS):
        worker = asyncio.create_task(quota_worker(i, broadcast_exchange))
        workers.append(worker)
    print(
        f"[Router] 已启动 {NUM_WORKERS} 个协程工人, 内部缓冲区: {MAX_QUEUE_SIZE}, "
        f"prefetch: {PREFETCH_COUNT}",
        flush=True,
    )

    # 2. 极速接收网络数据并塞入内部队列 (开启 no_ack=True)
    #    如果队列满了, await task_queue.put 会异步阻塞,
    #    自然限制了从 RabbitMQ 拉取数据的速度, 保护 CPU
    try:
        async with source_queue.iterator(no_ack=True) as queue_iter:
            async for message in queue_iter:
                if message.body:
                    await task_queue.put(message.body)
    except (asyncio.CancelledError, KeyboardInterrupt):
        print("\n[Router] 收到停止信号, 排空队列后退出...", flush=True)
        # 等待队列中残留任务处理完
        await task_queue.join()
        for w in workers:
            w.cancel()
    finally:
        print("[Router] 已停止。", flush=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[Router] 手动停止。")
