#!/usr/bin/env python3
"""
Demo1: RPC Client - 发送请求到队列1，从队列2接收应答

用法:
    python demo_rpc_client.py

依赖:
    pip install aio-pika
"""

import asyncio
import uuid
from datetime import datetime

import aio_pika
from aio_pika import ExchangeType, Message

from msgpacket import MsgPacket, MSG_TYPE_REQUEST, MSG_TYPE_PUSH


RABBITMQ_URL = "amqp://192.168.10.2:5672/"
EXCHANGE_NAME = "msgpacket.exchange"
QUEUE_REQ = "EvTrade.Testgs.Push"       # 队列1：接收请求（客户端→API）


async def main():
    # 连接 RabbitMQ
    conn = await aio_pika.connect_robust(RABBITMQ_URL)
    channel = await conn.channel()

    # 声明 exchange 和队列
    exchange = await channel.declare_exchange(
        EXCHANGE_NAME, ExchangeType.TOPIC, durable=True,
    )
    await channel.declare_queue(QUEUE_REQ, durable=True)

 
    try:
        # 发送 5 个请求到队列1
        for i in range(1):
            
            
            
            pkt = resp_pkt_ord_push(i)
            
            
            
            
            print(f"  {pkt.wire_to_string()}")
            
            _, wire_data = pkt.encode()
            # 发送到队列1
            await exchange.publish(
                Message(body=wire_data),
                routing_key=QUEUE_REQ,
            )
            #print(f"[Client] -> request[{seq}]: msg_id={msg_id}, "
            #      f"func=echo, seq={seq}, size={len(wire_data)}")
            #await asyncio.sleep(0.5)  # 0.5秒间隔
    except KeyboardInterrupt:
        print("\n[Client] Interrupted")
    finally:
        await asyncio.sleep(10)  # 等待最后一批回复到达
        await conn.close()
        print("[Client] Closed")


async def listen_replies(queue):
    """从队列2监听并打印应答"""
    print("[Client] Started listening on reply queue...")
    async with queue.iterator() as qiter:
        async for msg in qiter:
            async with msg.process():
                wire_data = msg.body
                try:
                    pkt = MsgPacket.decode(wire_data)
                    print(f"  {pkt.wire_to_string()}")
                except Exception as e:
                    print(f"[Client] decode error: {e}")

async def listen_pushs(queue):
    """从队列2监听并打印应答"""
    print("[Client] Started listening on push queue...")
    async with queue.iterator() as qiter:
        async for msg in qiter:
            async with msg.process():
                wire_data = msg.body
                try:
                    pkt = MsgPacket.decode(wire_data)
                    print(f"  {pkt.wire_to_string()}")
                except Exception as e:
                    print(f"[Client] decode error: {e}")
                    
def resp_pkt_ord(seq: int) -> MsgPacket:
    """发送请求到队列1"""
    # 构建请求包
    pkt = MsgPacket(MSG_TYPE_REQUEST, "V1.0")
    pkt.set_func("ord_stk")
    pkt.set_headers(5, "stock_code,volume,price_type,price,direction")
    pkt.add_row()
    pkt.set_value("stock_code", "000001.SZ")
    pkt.set_value("volume", "1000")
    pkt.set_value("price_type", "0")
    pkt.set_value("price", "11.12")
    pkt.set_value("direction", "BUY")
    pkt.set_value("remark", f"xtquant_test")
    pkt.finalize()
    
    return pkt

def resp_pkt_qry_ord(seq: int) -> MsgPacket:
    """发送请求到队列1"""
    # 构建请求包
    pkt = MsgPacket(MSG_TYPE_REQUEST, "V1.0")
    pkt.set_func("qry_ord")
    #pkt.set_value("data", f"request-{seq}")
    pkt.finalize()
    
    return pkt

def resp_pkt_qry_mch(seq: int) -> MsgPacket:
    """发送请求到队列1"""
    # 构建请求包
    pkt = MsgPacket(MSG_TYPE_REQUEST, "V1.0")
    pkt.set_func("qry_mch")
    #pkt.set_value("data", f"request-{seq}")
    pkt.finalize()
    
    return pkt
    
def resp_pkt_ord_push(seq: int) -> MsgPacket:
    """发送请求到队列1"""
    # 构建请求包
    pkt = MsgPacket(MSG_TYPE_PUSH, "V1.0")
    pkt.set_func("ord_cfm")
    pkt.set_headers(10, "order_id,stock_code,order_status,order_volume,traded_volume,price,traded_price, strategy_name,remark,order_time")
    pkt.add_row()
    pkt.set_value("order_id", "4343423")
    pkt.set_value("stock_code", "000001.SZ")
    pkt.set_value("order_status", "56")
    pkt.set_value("order_volume", "100")
    pkt.set_value("traded_volume", "100")
    pkt.set_value("price", "11.12")
    pkt.set_value("traded_price", "12.23")
    pkt.set_value("strategy_name", "evev") 
    pkt.set_value("remark", "10000032")
    pkt.set_value("order_time", "1991")
    pkt.finalize()
    
    return pkt
    
#PUSH:C6036399D84B40A297FCAE51622CA627#V1.0#####TP20260723133946236#trd_cfm##traded_id<ESC>_stock_code<ESC>_traded_volume<ESC>_traded_price<ESC>_strategy_name<ESC>_remark<ESC>\319257804013639<ESC>_000001.SZ<ESC>_100<ESC>_11.03<ESC>_<ESC>_10000028
def resp_pkt_match_push(seq: int) -> MsgPacket:
    """发送请求到队列1"""
    # 构建请求包
    pkt = MsgPacket(MSG_TYPE_PUSH, "V1.0")
    pkt.set_func("trd_cfm")
    pkt.set_headers(6, "traded_id,stock_code,traded_volume,traded_price,strategy_name,remark")
    pkt.add_row()
    pkt.set_value("traded_id", "2323232")
    pkt.set_value("stock_code", "000001.SZ")
    pkt.set_value("traded_volume", "100")
    pkt.set_value("traded_price", "12.23")
    pkt.set_value("strategy_name", "ysysysys")
    pkt.set_value("remark", f"10000032")
    pkt.finalize()
    
    return pkt
    
if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        print("\n[Client] Exited")
    finally:
        loop.close()