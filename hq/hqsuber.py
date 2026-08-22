#!/usr/bin/env python3
# -*- coding: gbk -*-
"""
下游策略/程序：按标的订阅行情客户端示例
"""

import asyncio
import aio_pika

RABBITMQ_URL = "amqp://192.168.10.2:5672/"
BROADCAST_EXCHANGE = "quota.broadcast.exchange"

# ==================== 在这里配置你想订阅的标的 ====================
# 支持精确代码，也支持通配符（* 代表匹配一个词）
SUBSCRIBE_STOCKS = [
    "588710.SH", 
    "518880.SH"
    #"*.SH"        # 顺便订阅所有上海证券交易所的标的 (测试通配)
]

async def on_receive_stock_quote(message: aio_pika.IncomingMessage):
    """收到订阅标的行情的回调函数"""
    async with message.process():
        routing_key = message.routing_key
        body = message.body.decode('gbk')
        
        # 在这里写你的交易策略触发逻辑
        print(f" [接收成功] 标的: {routing_key} | 行情数据: {body}")

async def main():
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    channel = await connection.channel()

    # 1. 获取广播交换机
    exchange = await channel.declare_exchange(
        BROADCAST_EXCHANGE, 
        type=aio_pika.ExchangeType.TOPIC, 
        durable=True
    )

    # 2. 声明一个专属的、临时的排他队列（exclusive=True）
    # 当此订阅程序关闭时，该队列会自动销毁，不会在 MQ 中残留垃圾数据
    client_queue = await channel.declare_queue(exclusive=True)

    # 3. 核心：根据订阅列表，将队列绑定到交换机对应的路由键上
    for stock in SUBSCRIBE_STOCKS:
        await client_queue.bind(exchange, routing_key=stock)
        print(f"[Client] 成功订阅标的: {stock}")

    print("[Client] 订阅成功，正在等待目标行情推送...\n")

    # 4. 开始消费属于自己的定制行情
    async with client_queue.iterator() as queue_iter:
        async for message in queue_iter:
            await on_receive_stock_quote(message)

if __name__ == "__main__":
    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        print("\n[Client] 订阅程序退出。")
    finally:
        loop.close()