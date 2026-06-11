#!/usr/bin/env python3
# -*- coding: gbk -*-
"""
EvQuota 行情并发消费与精准分发路由器 (Python 3.6.8 修复版)
"""

import asyncio
import aio_pika

# ==================== 配置 ====================
RABBITMQ_URL = "amqp://192.168.10.2:5672/"
SOURCE_QUEUE = "EvQuota"  # QMT 塞入的原始行情队列

# 新设一个专用于广播分发的 Topic 交换机
BROADCAST_EXCHANGE = "quota.broadcast.exchange" 

# 并发处理限制（QoS Prefetch）：允许同时并发处理的未确认消息数
CONCURRENCY_LIMIT = 50 

async def process_message(message: aio_pika.IncomingMessage, exchange: aio_pika.Exchange):
    """单条行情的解析与二次转发逻辑"""
    async with message.process():
        try:
            # 1. 解码行情数据
            body_str = message.body.decode('gbk').strip()
            if not body_str:
                return
            
            # 2. 提取股票代码
            fields = body_str.split('|')
            stock_code = fields[0]  # 例如: "600519.SH"
            
            # 3. 封装并重新发布
            # 核心修复：直接使用数字 1 代替 aio_pika.DeliveryMode.TRANSIENT
            forward_msg = aio_pika.Message(
                body=message.body,
                delivery_mode=1  # 1 代表非持久化(Transient)，在 Python 3.6 环境下最稳定且性能最高
            )
            
            # 发送到广播交换机，路由键是股票代码
            await exchange.publish(forward_msg, routing_key=stock_code)
            
        except Exception as e:
            # 这里的 str(e) 之前打印出了 "TRANSIENT"，正是因为原代码在封装 Message 时崩溃了
            print(f"[Error] 解析或分发失败: {e}")

async def main():
    print(f"[Router] 正在连接 RabbitMQ: {RABBITMQ_URL}...", flush=True)
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    channel = await connection.channel()
    
    # 限制通道上的并发流量
    await channel.set_qos(prefetch_count=CONCURRENCY_LIMIT)

    # 1. 声明原始行情队列
    source_queue = await channel.declare_queue(SOURCE_QUEUE, durable=True)

    # 2. 声明专门用于订阅的 Topic 广播交换机
    broadcast_exchange = await channel.declare_exchange(
        BROADCAST_EXCHANGE, 
        type=aio_pika.ExchangeType.TOPIC, 
        durable=True
    )

    print(f"[Router] 开始并发消费队列 [{SOURCE_QUEUE}] 并分发至 [{BROADCAST_EXCHANGE}]...", flush=True)

    loop = asyncio.get_event_loop()

    # 3. 开始异步循环消费
    async with source_queue.iterator() as queue_iter:
        async for message in queue_iter:
            loop.create_task(process_message(message, broadcast_exchange))

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        print("\n[Router] 程序被手动停止。")
    finally:
        print("[Router] 正在清理底层异步资源...")
        loop.close()