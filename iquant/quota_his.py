#coding:gbk
"""
==============================================================================
iQuant / QMT 策略服务：极简文本流应答引擎 (已重构，完美兼容闭环消费机制)
==============================================================================
"""

import queue
import threading
import datetime
import time
import pika
import pandas as pd
from msgpacket import MsgPacket, MSG_TYPE_ANSWER
from typing import Callable, Dict, List, Optional, Tuple, Any

# ================================================================
# 1. 基础配置与全局队列
# ================================================================
class Config:
    HOST = "192.168.10.2"
    PORT = 5672
    USER = "guest"
    PASS = "guest"
    VHOST = "/"
    
    EXCHANGE_NAME = "quota_his.exchange"
    QUEUE_REQ = "EvTrade.Testgs.ReqHisHq"
    ACCOUNT_ID = '110000035080'

config = Config()

GLOBAL_REQ_QUEUE = queue.Queue()   # 请求队列 (MQ 线程 -> QMT 主线程)
GLOBAL_ANS_QUEUE = queue.Queue()   # 应答队列 (QMT 主线程 -> MQ 线程) [(target_queue, bytes)]

GLOBAL_STORE = {
    "mq_conn": None,
    "mq_thread": None,
}

# ================================================================
# 2. Handler 注册与分发引擎
# ================================================================
HandlerReturn = Tuple[str, str, Optional[str]]
HandlerFunc = Callable[[Any, MsgPacket], HandlerReturn]

_HANDLERS: Dict[str, HandlerFunc] = {}

def handler(func_name: str) -> Callable[[HandlerFunc], HandlerFunc]:
    def decorator(func: HandlerFunc) -> HandlerFunc:
        _HANDLERS[func_name] = func
        return func
    return decorator

def handle_trade_request(context, pkt: MsgPacket) -> HandlerReturn:
    func = pkt.func().strip('\x00')
    print(1)
    handler_func = _HANDLERS.get(func)
    print(func)
    if handler_func is None:
        print(2)
        return "99999", f"Unknown func: {func}", None
    try:
        print(3)
        return handler_func(context, pkt)
    except Exception as e:
        return "99999", f"Execution error: {str(e)}", None

# ================================================================
# 3. 业务 Handler: 极速文本拼接行情 (his_hq)
# ================================================================
@handler("his_hq")
def _h_his_hq(context, pkt: MsgPacket) -> HandlerReturn:
    try:
        stock_code = pkt.get_value_str("stock_code").strip()
        start_date_str = pkt.get_value_str("start_date").strip()
        end_date_str = pkt.get_value_str("end_date").strip()
        ans_queue = pkt.get_value_str("ans_queue").strip()

    except (ValueError, TypeError) as e:
        print(f"参数类型错误: {e}")

    if not start_date_str or not stock_code or not ans_queue:
        return "10001", "Missing required parameters!", None

    if not end_date_str:
        end_date_str = datetime.datetime.now().strftime("%Y%m%d")

    try:
        start_date = datetime.datetime.strptime(start_date_str[:8], "%Y%m%d").date()
        end_date = datetime.datetime.strptime(end_date_str[:8], "%Y%m%d").date()
    except Exception as e:
        return "10004", f"Date format error: {str(e)}", None

    current_date = start_date
    total_days_processed = 0

    print(f"[HQ Service] 开始按日获取行情: {stock_code} ({start_date_str} ~ {end_date_str})...")

    query_fields = ['close'] 

    while current_date <= end_date:
        day_str = current_date.strftime("%Y%m%d")
        
        market_data = context.get_market_data_ex(
            fields=query_fields,
            stock_code=[stock_code],
            period='1m',
            start_time=f"{day_str}093100",
            end_time=f"{day_str}150000",
            count=-1,
            dividend_type='follow',
            fill_data=True,
            subscribe=False
        )
        
        df = market_data.get(stock_code)
        print(df)
        if df is not None and not df.empty:
            try:
                stimes = df.index.astype(str).tolist()
                
                if len(query_fields) == 1:
                    col_vals = df[query_fields[0]].astype(str).tolist()
                    rows_str = [f"{st}#{val}" for st, val in zip(stimes, col_vals)]
                else:
                    rows_str = [
                        f"{st}#" + "#".join(row) 
                        for st, row in zip(stimes, df[query_fields].astype(str).values)
                    ]

                payload_str = "|".join(rows_str)
                print(payload_str)
                # 将目标队列和字节串塞入 GLOBAL_ANS_QUEUE
                GLOBAL_ANS_QUEUE.put((ans_queue, payload_str.encode('utf-8')))
                total_days_processed += 1
                print(f"[HQ Service] 成功推送 {day_str} 数据至 {ans_queue}，共 {len(df)} 行")

            except Exception as e:
                print(f"[HQ Service] 处理 {day_str} 数据拼接异常: {e}")

        current_date += datetime.timedelta(days=1)

    print(f"[HQ Service] 行情读取完成，共投递 {total_days_processed} 天。")
    return "00000", f"Success", None

# ================================================================
# 4. MQ 核心线程 (使用模板中验证成功的 channel.consume 模式)
# ================================================================
def rabbitmq_worker(ContextInfo):
    print(f"[MQ 线程] 开始连接 RabbitMQ ({config.HOST}:{config.PORT})...")
    conn = None
    try:
        credentials = pika.PlainCredentials(config.USER, config.PASS)
        params = pika.ConnectionParameters(
            host=config.HOST, port=config.PORT, virtual_host=config.VHOST,
            credentials=credentials, socket_timeout=5
        )
        conn = pika.BlockingConnection(params)
        channel = conn.channel()

        GLOBAL_STORE["mq_conn"] = conn

        # 声明 Exchange 和 请求 Queue
        channel.exchange_declare(exchange=config.EXCHANGE_NAME, exchange_type='topic', durable=True)
        channel.queue_declare(queue=config.QUEUE_REQ, durable=True)
        channel.queue_bind(queue=config.QUEUE_REQ, exchange=config.EXCHANGE_NAME, routing_key=config.QUEUE_REQ)
        channel.basic_qos(prefetch_count=1)

        declared_queues = set()

        def process_send_queue():
            """刷出 GLOBAL_ANS_QUEUE 中的待发数据并动态投递到客户端队列"""
            while not GLOBAL_ANS_QUEUE.empty():
                try:
                    target_queue, msg_bytes = GLOBAL_ANS_QUEUE.get_nowait()
                    if channel.is_open:
                        # 确保客户端目标队列存在
                        if target_queue not in declared_queues:
                            channel.queue_declare(queue=target_queue, durable=True)
                            declared_queues.add(target_queue)

                        channel.basic_publish(
                            exchange='',
                            routing_key=target_queue,
                            body=msg_bytes
                        )
                except queue.Empty:
                    break
                except Exception as e:
                    print(f"[MQ 发送异常]: {e}")

        print("[MQ 线程] 订阅成功，进入收发交替通道...")

        # 核心修复：使用 consume 驱动循环，兼顾接收与发送
        for message_metadata, properties, body in channel.consume(queue=config.QUEUE_REQ, inactivity_timeout=0.2):
            if not getattr(ContextInfo, 'is_running', False):
                print("[MQ 线程] 收到策略停止信号，准备退出循环...")
                break

            # A. 优先刷出待发行情数据
            process_send_queue()

            # B. 收到请求报文，塞入全局请求队列
            if body is not None:
                GLOBAL_REQ_QUEUE.put(body)
                channel.basic_ack(delivery_tag=message_metadata.delivery_tag)

    except pika.exceptions.AMQPConnectionError:
        print("[MQ 线程] Socket 连接已被主程序主动关停，线程打断成功。")
    except Exception as e:
        print(f"[MQ 线程异常]: {e}")
    finally:
        GLOBAL_STORE["mq_conn"] = None
        print("[MQ 线程] 已完全退出并销毁！")

# ================================================================
# 5. QMT 策略生命周期 & runtime 定时器
# ================================================================
def init(ContextInfo):
    print("==================================================")
    print("iQuant 历史行情极速服务引擎启动...")
    print("==================================================")
    ContextInfo.is_running = True
    ContextInfo.set_account(config.ACCOUNT_ID)

    t = threading.Thread(target=rabbitmq_worker, args=(ContextInfo,), daemon=True)
    GLOBAL_STORE["mq_thread"] = t
    t.start()

    ContextInfo.run_time("check_and_process", "100nMilliSecond", "2020-01-01 00:00:00")

def check_and_process(ContextInfo):
    if not getattr(ContextInfo, 'is_running', False):
        return

    while not GLOBAL_REQ_QUEUE.empty():
        try:
            msg_recv = GLOBAL_REQ_QUEUE.get_nowait()
            pkt = MsgPacket.decode(msg_recv)
            handle_trade_request(ContextInfo, pkt)
        except queue.Empty:
            break
        except Exception as e:
            print(f"[runtime 处理异常]: {e}")

def stop(ContextInfo):
    print("\n==================================================")
    print("收到停止指令，开始关停行情服务...")
    print("==================================================")
    ContextInfo.is_running = False

    conn = GLOBAL_STORE.get("mq_conn")
    if conn:
        try:
            if getattr(conn, 'is_open', False) and not getattr(conn, 'is_closed', True):
                conn.close()
        except Exception:
            pass

    t = GLOBAL_STORE.get("mq_thread")
    if t and t.is_alive():
        t.join(timeout=1.0)

    while not GLOBAL_REQ_QUEUE.empty():
        try: GLOBAL_REQ_QUEUE.get_nowait()
        except: break
    while not GLOBAL_ANS_QUEUE.empty():
        try: GLOBAL_ANS_QUEUE.get_nowait()
        except: break

    print("行情服务清理完毕，成功停止。")

