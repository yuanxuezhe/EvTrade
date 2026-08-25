#coding:gbk
"""
==============================================================================
iQuant / QMT ���Է��񣺼����ı���Ӧ������ (���ع����������ݱջ����ѻ���)
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
# 1. ����������ȫ�ֶ���
# ================================================================
class Config:
    HOST = "192.168.10.2"
    PORT = 5672
    USER = "guest"
    PASS = "guest"
    VHOST = "/"
    
    EXCHANGE_NAME = "quota_his.exchange"
    QUEUE_REQ = "EvTrade.ReqHisHq"
    ACCOUNT_ID = '110000035080'

config = Config()

GLOBAL_REQ_QUEUE = queue.Queue()   # ������� (MQ �߳� -> QMT ���߳�)
GLOBAL_ANS_QUEUE = queue.Queue()   # Ӧ����� (QMT ���߳� -> MQ �߳�) [(target_queue, bytes)]

GLOBAL_STORE = {
    "mq_conn": None,
    "mq_thread": None,
}

# ================================================================
# 2. Handler ע����ַ�����
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
# 3. ҵ�� Handler: �����ı�ƴ������ (his_hq)
# ================================================================
@handler("his_hq")
def _h_his_hq(context, pkt: MsgPacket) -> HandlerReturn:
    try:
        stock_code = pkt.get_value_str("stock_code").strip()
        start_date_str = pkt.get_value_str("start_date").strip()
        end_date_str = pkt.get_value_str("end_date").strip()
        ans_queue = pkt.get_value_str("ans_queue").strip()
        fields_str = pkt.get_value_str("fields").strip()
        period = pkt.get_value_str("period").strip()

    except (ValueError, TypeError) as e:
        print(f"�������ʹ���: {e}")

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

    print(f"[HQ Service] ��ʼ���ջ�ȡ����: {stock_code} ({start_date_str} ~ {end_date_str})...")

    query_fields = [f.strip() for f in fields_str.split(",") if f.strip()] if fields_str else ["close"]
    query_period = period.strip() if period else "1m"
    if query_period not in ("tick", "1m", "5m", "15m", "30m", "1h", "1d"):
        return "10005", f"Unsupported period: {query_period}", None

    # col_header = stime + query_fields (first line of response)
    col_header = "stime," + ",".join(query_fields) 

    while current_date <= end_date:
        day_str = current_date.strftime("%Y%m%d")
        
        market_data = context.get_market_data_ex(
            fields=query_fields,
            stock_code=[stock_code],
            period=query_period,
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
                # ��Ŀ����к��ֽڴ����� GLOBAL_ANS_QUEUE
                GLOBAL_ANS_QUEUE.put((ans_queue, (col_header + '\n' + payload_str).encode('utf-8')))
                total_days_processed += 1
                print(f"[HQ Service] �ɹ����� {day_str} ������ {ans_queue}���� {len(df)} ��")

            except Exception as e:
                print(f"[HQ Service] ���� {day_str} ����ƴ���쳣: {e}")

        current_date += datetime.timedelta(days=1)

    print(f"[HQ Service] �����ȡ��ɣ���Ͷ�� {total_days_processed} �졣")
    return "00000", f"Success", None

# ================================================================
# 4. MQ �����߳� (ʹ��ģ������֤�ɹ��� channel.consume ģʽ)
# ================================================================
def rabbitmq_worker(ContextInfo):
    print(f"[MQ �߳�] ��ʼ���� RabbitMQ ({config.HOST}:{config.PORT})...")
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

        # ���� Exchange �� ���� Queue
        channel.exchange_declare(exchange=config.EXCHANGE_NAME, exchange_type='topic', durable=True)
        channel.queue_declare(queue=config.QUEUE_REQ, durable=True)
        channel.queue_bind(queue=config.QUEUE_REQ, exchange=config.EXCHANGE_NAME, routing_key=config.QUEUE_REQ)
        channel.basic_qos(prefetch_count=1)

        declared_queues = set()

        def process_send_queue():
            """ˢ�� GLOBAL_ANS_QUEUE �еĴ������ݲ���̬Ͷ�ݵ��ͻ��˶���"""
            while not GLOBAL_ANS_QUEUE.empty():
                try:
                    target_queue, msg_bytes = GLOBAL_ANS_QUEUE.get_nowait()
                    if channel.is_open:
                        # ȷ���ͻ���Ŀ����д���
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
                    print(f"[MQ �����쳣]: {e}")

        print("[MQ �߳�] ���ĳɹ��������շ�����ͨ��...")

        # �����޸���ʹ�� consume ����ѭ������˽����뷢��
        for message_metadata, properties, body in channel.consume(queue=config.QUEUE_REQ, inactivity_timeout=0.2):
            if not getattr(ContextInfo, 'is_running', False):
                print("[MQ �߳�] �յ�����ֹͣ�źţ�׼���˳�ѭ��...")
                break

            # A. ����ˢ��������������
            process_send_queue()

            # B. �յ������ģ�����ȫ���������
            if body is not None:
                GLOBAL_REQ_QUEUE.put(body)
                channel.basic_ack(delivery_tag=message_metadata.delivery_tag)

    except pika.exceptions.AMQPConnectionError:
        print("[MQ �߳�] Socket �����ѱ�������������ͣ���̴߳�ϳɹ���")
    except Exception as e:
        print(f"[MQ �߳��쳣]: {e}")
    finally:
        GLOBAL_STORE["mq_conn"] = None
        print("[MQ �߳�] ����ȫ�˳������٣�")

# ================================================================
# 5. QMT ������������ & runtime ��ʱ��
# ================================================================
def init(ContextInfo):
    print("==================================================")
    print("iQuant ��ʷ���鼫�ٷ�����������...")
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
            print(f"[runtime �����쳣]: {e}")

def stop(ContextInfo):
    print("\n==================================================")
    print("�յ�ָֹͣ���ʼ��ͣ�������...")
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
        except queue.Empty: break
    while not GLOBAL_ANS_QUEUE.empty():
        try: GLOBAL_ANS_QUEUE.get_nowait()
        except queue.Empty: break

    print("�������������ϣ��ɹ�ֹͣ��")

