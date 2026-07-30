#coding:gbk
"""
==============================================================================
iQuant / QMT ���Լ���ģ�壺˫���� MQ �ջ�ͨ�����̰߳�ȫ����
==============================================================================
��ת·����
1. [MQ �߳�] channel.consume ���� MQ ������� ? ���� GLOBAL_REQ_QUEUE
2. [QMT ���߳�] run_time(100ms) ȡ�� GLOBAL_REQ_QUEUE  ��ӡ  ���� GLOBAL_ANS_QUEUE
3. [MQ �߳�] ������ GLOBAL_ANS_QUEUE ������ ? basic_publish Ͷ�ݵ� MQ Ӧ�����
4. [stop ����] �����ر� Connection ��� Socket ���� ? 100% ���������߳� ? ��ղ�������
"""

import queue
import threading
import pika
from msgpacket import MsgPacket, MSG_TYPE_ANSWER, MSG_TYPE_PUSH
from typing import Callable, Dict, List, Optional, Tuple

# ================================================================
# 1. ����������ȫ�ֶ���/����
# ================================================================
class Config:
    HOST = "192.168.10.2"
    PORT = 5672
    USER = "guest"
    PASS = "guest"
    VHOST = "/"
    
    EXCHANGE_NAME = "msgpacket.exchange"
    QUEUE_REQ = "EvTrade.Test.Req"
    QUEUE_REPLY = "EvTrade.Test.Reply"
    QUEUE_PUSH = "EvTrade.Test.Push"
    ACCOUNT_ID = '410001265100'
    # 410001265100   170000062910
config = Config()

ORDER_TYPE_STOCK = 1101
QUICK_TRADE_MODEL = 1
STRATEGY_NAME = 'EvTrade-Strategy'
# ȫ���̰߳�ȫ����
GLOBAL_REQ_QUEUE = queue.Queue()  # ������� (MQ �߳�  ���߳�)
GLOBAL_ANS_QUEUE = queue.Queue()  # Ӧ����� (���߳�   MQ �߳�)
GLOBAL_PUSH_QUEUE = queue.Queue()  # Ӧ����� (���߳�   MQ �߳�)
# ȫ�������ھ���洢
GLOBAL_STORE = {
    "mq_conn": None,   # �洢 Connection������ stop() ������� Socket ����
    "mq_thread": None, # �洢 Thread �������� join ȷ���˳�
}

# ================================================================
# Handler ע������ӿ�
# ================================================================
#: Return: (code: str, msg: str, data: Optional[List[Dict]])
HandlerReturn = Tuple[str, str, Optional[List[Dict]]]
HandlerFunc = Callable[[MsgPacket], HandlerReturn]

_HANDLERS: Dict[str, HandlerFunc] = {}


def handler(func_name: str) -> Callable[[HandlerFunc], HandlerFunc]:
    """Handler ע��װ����"""
    def decorator(func: HandlerFunc) -> HandlerFunc:
        _HANDLERS[func_name] = func
        return func
    return decorator


def handle_trade_request(context: ContextInfo, pkt: MsgPacket) -> HandlerReturn:
    """�ַ��������󵽶�Ӧ handler"""
    func = pkt.func().strip('\x00')

    handler = _HANDLERS.get(func)
    if handler is None:
        return "99999", f"unknown func: {func}", None
    try:
        return handler(context, pkt)
    except Exception as e:
        return "99999", str(e), None


# ================================================================
# ��ѯ�� Handler
# ================================================================

@handler("qry_pos")
def _h_qry_pos(_context: ContextInfo, _pkt: MsgPacket) -> HandlerReturn:
    """��ѯ�ֲ�"""
    positions = get_trade_detail_data(config.ACCOUNT_ID, 'STOCK', 'POSITION')
    return "00000", "ok", [{
        "stock_code": pos.m_strInstrumentID + '.' + pos.m_strExchangeID,
        "last_vol": pos.m_nYesterdayVolume,
        "volume": pos.m_nVolume,
        "avl_amt": pos.m_nCanUseVolume,
        "avg_price": pos.m_dOpenPrice,
    } for pos in positions]


@handler("qry_ord")
def _h_qry_ord(_context: ContextInfo, _pkt: MsgPacket) -> HandlerReturn:
    """��ѯ����"""
    #orders = state.xt_trader.query_stock_orders(state.xt_acc)
    orders = get_trade_detail_data(config.ACCOUNT_ID, 'STOCK', 'ORDER')
    return "00000", "ok", [{
        "order_id": order.m_strOrderSysID,
        "stock_code": order.m_strInstrumentID + '.' + order.m_strExchangeID,
        "price": order.m_dLimitPrice,
        "order_volume": order.m_nVolumeTotalOriginal,
        "traded_volume": order.m_nVolumeTraded,
        "traded_price": order.m_dTradedPrice,
        "order_status": order.m_nOrderStatus,
        "status_msg": order.m_strErrorMsg,
        "strategy_name": '',
        "order_remark": order.m_strRemark,
        "order_time": order.order_time,
    } for order in orders]


@handler("qry_ast")
def _h_qry_ast(_context: ContextInfo, _pkt: MsgPacket) -> HandlerReturn:
    """��ѯ�ʲ�"""
    assets = get_trade_detail_data(config.ACCOUNT_ID, 'stock', 'account')
    #if asset is None:
    #    return "99999", "��ѯ�ʲ�ʧ��", None
    return "00000", "ok", [{
        "cash": asset.m_dAvailable,
        "available": asset.m_dAvailable,
        "frozen_cash": asset.m_dFrozenCash,
        "market_value": asset.m_dInstrumentValue,
        "total_asset": asset.m_dBalance,
        "last_asset": asset.m_dInitBalance,
        "PreBalance": asset.m_dPreBalance,
    }for asset in assets]


@handler("qry_mch")
def _h_qry_mch(_context: ContextInfo, _pkt: MsgPacket) -> HandlerReturn:
    """��ѯ�ɽ�"""
    #trades = state.xt_trader.query_stock_trades(state.xt_acc)
    trades = get_trade_detail_data(config.ACCOUNT_ID, 'STOCK', 'DEAL')
    return "00000", "ok", [{
        "order_id": trade.m_strOrderSysID,
        "traded_id": trade.m_strTradeID,
        "stock_code": trade.m_strInstrumentID + '.' + trade.m_strExchangeID,
        "traded_volume": trade.m_nVolume,
        "traded_price": trade.m_dPrice,
        "traded_amount": trade.traded_amount,
        "strategy_name": '',
        "order_remark": trade.m_strRemark,
        "traded_time": trade.traded_time,
    } for trade in trades]


# ================================================================
# ������ Handler
# ================================================================

@handler("ord_stk")
def _h_ord_stk(context: ContextInfo, pkt: MsgPacket) -> HandlerReturn:
    """�첽�µ��������"""
    try:
        # 1. ������ȡ�������������ṹ������������ȷ��
        stock_code = pkt.get_value_str("stock_code")
        order_type = int(pkt.get_value_str("order_type"))
        price_type = int(pkt.get_value_str("price_type"))
        volume = float(pkt.get_value_str("volume"))
        price = float(pkt.get_value_str("price"))
        remark = pkt.get_value_str("remark")
    except (ValueError, TypeError) as e:
        return "99999", f"�������ʹ���: {e}", []

    # 2. ����ҵ��У�飨��ֹ��Ч/Σ�ձ��ģ�
    if volume <= 0:
        return "99998", f"�µ�����[{volume}]�������0", []
    
    # 4. ִ���µ�ָ��
    passorder(
        order_type,           # 23: ���� / 24: ���� ��
        ORDER_TYPE_STOCK,     # 1101 ��������
        config.ACCOUNT_ID,    # �ʽ��˺�
        stock_code,           # ��Ĵ���
        price_type,           # ��������
        price,                # �����۸�
        volume,               # ��������
        STRATEGY_NAME,        # ��������
        QUICK_TRADE_MODEL,    # ��ݽ��ױ�ʶ
        remark,               # ��ע
        context               # ����������
    )

    return "00000", "ok", [{"seq": 1}]


@handler("cxl_ord")
def _h_cxl_ord(context: ContextInfo, pkt: MsgPacket) -> HandlerReturn:
    """cancel order (xtquant API takes only acc + order_id, no market/stock_code)"""
    order_id = pkt.get_value_str("order_id")
    cancel(order_id, config.ACCOUNT_ID, 'STOCK', context)

    #result = state.xt_trader.cancel_order_stock_async(state.xt_acc, order_id)
    return "00000", "ok", [{"result": 1}]

# ================================================================
# ���ͻذ�
# ================================================================

def order_callback(ContextInfo, orderInfo):
    """ί��ȷ��"""
    push_event("ord_cfm", [{
        "order_id": orderInfo.m_strOrderSysID,
        "stock_code": orderInfo.m_strInstrumentID + '.' + orderInfo.m_strExchangeID,
        "order_status": orderInfo.m_nOrderStatus,
        "order_volume": orderInfo.m_nVolumeTotalOriginal,
        "traded_volume": orderInfo.m_nVolumeTraded,
        "price": orderInfo.m_dLimitPrice,
        "traded_price": orderInfo.m_dTradedPrice,
        "strategy_name": '',
        "remark": orderInfo.m_strRemark,
        "order_time": orderInfo.m_strInsertDate + orderInfo.m_strInsertTime,
    }])

def deal_callback(ContextInfo, dealInfo):
    """ 成交通报 """
    stock_code = dealInfo.m_strInstrumentID + '.' + dealInfo.m_strExchangeID
    push_event("trd_cfm", [{
        "traded_id": dealInfo.m_strTradeID,
        "stock_code": stock_code,
        "traded_volume": dealInfo.m_nVolume,
        "traded_price": dealInfo.m_dPrice,
        "strategy_name": '',
        "remark": dealInfo.m_strRemark,
    }])
    # v118.4: 成交后立即推送该标的最新持仓快照，确保前后端持仓数据同步
    #   broker position_callback 可能不及时，trd_cfm 路径兜底保证持仓刷新
    try:
        positions = get_trade_detail_data(config.ACCOUNT_ID, 'STOCK', 'POSITION')
        for p in positions:
            if p.m_strInstrumentID + '.' + p.m_strExchangeID == stock_code:
                push_event("pos_push", [{
                    "stock_code": stock_code,
                    "last_vol": p.m_nYesterdayVolume,
                    "volume": p.m_nVolume,
                    "avl_amt": p.m_nCanUseVolume,
                    "avg_price": p.m_dOpenPrice,
                }])
                break
    except Exception as e:
        print(f"[deal_callback] pos_push fallback failed: {e}")
    
def position_callback(ContextInfo, positonInfo):
    """ �ֲ����� """
    push_event("pos_push", [{
        "stock_code": positonInfo.m_strInstrumentID + '.' + positonInfo.m_strExchangeID,
        "last_vol": positonInfo.m_nYesterdayVolume,
        "volume": positonInfo.m_nVolume,
        "avl_amt": positonInfo.m_nCanUseVolume,
        "avg_price": positonInfo.m_dOpenPrice,
    }])

# ================================================================
# Ӧ�����
# ================================================================
def build_answer(pkt: MsgPacket, req_msg_id: str,
                 code: str, msg: str, data: List[Dict]) -> MsgPacket:
    """�� msgpacket ��ʽ��Ӧ���
    code != 0: RS1={code,msg}
    code == 0: RS1={code,msg} + RS2=data��
    """
    ans = MsgPacket(MSG_TYPE_ANSWER, pkt.version())
    ans.set_msg_id(req_msg_id)
    ans.set_func(pkt.func().strip('\x00'))

    # RS1: code + msg
    ans.set_headers(2, "code,msg")
    ans.add_row()
    ans.set_value("code", code)
    ans.set_value("msg", msg)

    # RS2: ���ݱ� (code==0 ��������ʱ����)
    if code == "00000" and data:
        ans.add_result_set()
        cols = list(data[0].keys())
        ans.set_headers(len(cols), ",".join(cols))
        for row in data:
            ans.add_row()
            for col in cols:
                ans.set_value(col, str(row.get(col, "")))

    ans.finalize()
    return ans

def push_event(func: str, data: List[Dict]) -> None:
    """�̰߳�ȫ�������¼��� RabbitMQ"""
    _mq_publish(func, data)

def _mq_publish(func: str, data: List[Dict]) -> None:
    """������Ϣ: func=���ܺ�, data=RS1���ݱ�"""
    try:
        pkt = MsgPacket(MSG_TYPE_PUSH)
        pkt.set_func(func)
        #pkt.set_timestamp(datetime.now().strftime('%Y%m%d%H%M%S%f')[:-3])

        if data:
            cols = list(data[0].keys())
            pkt.set_headers(len(cols), ",".join(cols))
            for row in data:
                pkt.add_row()
                for col in cols:
                    pkt.set_value(col, str(row.get(col, "")))
        else:
            pkt.set_headers(0, "")

        pkt.finalize()
        print(f"PUSH:{pkt.wire_to_string()}")
        _, msg_push = pkt.encode()
        # ��Ӧ����Ϣ��Ϣ����ȫ��Ӧ����У����� MQ �̷߳���
        GLOBAL_PUSH_QUEUE.put(msg_push)
    except Exception as e:
        print(f"[Push] ʧ�� {func}: {e}", flush=True)
        
# ================================================================
# 2. MQ �����̣߳��������� + ����Ӧ����з��ͣ�
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

        # �������Ӷ��󣬹� stop() ��ʱ��ȫ���
        GLOBAL_STORE["mq_conn"] = conn

        # ���� Exchange �� Queues
        channel.exchange_declare(exchange=config.EXCHANGE_NAME, exchange_type='topic', durable=True)
        channel.queue_declare(queue=config.QUEUE_REQ, durable=True)
        channel.queue_bind(queue=config.QUEUE_REQ, exchange=config.EXCHANGE_NAME, routing_key=config.QUEUE_REQ)
        channel.queue_declare(queue=config.QUEUE_REPLY, durable=True)

        channel.basic_qos(prefetch_count=1)
        print("[MQ �߳�] ���ĳɹ��������շ�����ͨ��...")

        def process_send_queue():
            """ˢ�� GLOBAL_ANS_QUEUE �еĴ������ݲ�Ͷ�ݵ� RabbitMQ"""
            while not GLOBAL_ANS_QUEUE.empty():
                try:
                    msg_bytes = GLOBAL_ANS_QUEUE.get_nowait()
                    if channel.is_open:
                        channel.basic_publish(
                            exchange='',  # ֱ��Ͷ�ݵ�ָ�����Ƶ�Ӧ�����
                            routing_key=config.QUEUE_REPLY,
                            body=msg_bytes
                        )
                        #print(f"[send]: {msg_bytes.wire_to_string()}")
                except queue.Empty:
                    break
                except Exception as e:
                    print(f"[MQ �����쳣]: {e}")
                    
            """ˢ�� GLOBAL_PUSH_QUEUE �еĴ������ݲ�Ͷ�ݵ� RabbitMQ"""
            while not GLOBAL_PUSH_QUEUE.empty():
                try:
                    msg_bytes = GLOBAL_PUSH_QUEUE.get_nowait()
                    if channel.is_open:
                        channel.basic_publish(
                            exchange='',  # ֱ��Ͷ�ݵ�ָ�����Ƶ�Ӧ�����
                            routing_key=config.QUEUE_PUSH,
                            body=msg_bytes
                        )
                        #print(f"[send]: {msg_bytes.wire_to_string()}")
                except queue.Empty:
                    break
                except Exception as e:
                    print(f"[MQ �����쳣]: {e}")
        
        # ʹ�� consume + inactivity_timeout ʵ�ֶ��Ľ�����Ӧ���͵Ľ�������
        for message_metadata, properties, body in channel.consume(queue=config.QUEUE_REQ, inactivity_timeout=0.2):
            # ֹͣ�ź��ж�
            if not getattr(ContextInfo, 'is_running', False):
                print("[MQ �߳�] �յ�����ֹͣ�źţ�׼���˳�ѭ��...")
                break

            # A. ���Ƚ�ȫ��Ӧ������е�����ˢ�� MQ
            process_send_queue()

            # B. �����յ������ģ�����ȫ���������
            if body is not None:
                GLOBAL_REQ_QUEUE.put(body)
                channel.basic_ack(delivery_tag=message_metadata.delivery_tag)

    except pika.exceptions.AMQPConnectionError:
        print("[MQ �߳�] Socket �����ѱ�������������ͣ���̴߳�ϳɹ���")
    except Exception as e:
        print(f"[MQ �߳��쳣]: {e}")
    finally:
        # ע�⣺����ֻ��վ������Ҫ�ظ����� conn.close()
        # ��Ϊ stop() ���Ѿ����� close ���ˣ������������쳣�����ѹر�
        GLOBAL_STORE["mq_conn"] = None
        print("[MQ �߳�] ����ȫ�˳������٣�")

# ================================================================
# 3. QMT ������������ & runtime ��ʱ��
# ================================================================
def init(ContextInfo):
    print("==================================================")
    print("iQuant ˫���м����շ����� ����...")
    print("==================================================")
    ContextInfo.is_running = True
    ContextInfo.set_account(config.ACCOUNT_ID)
    # 1. �������� MQ �߳�
    t = threading.Thread(target=rabbitmq_worker, args=(ContextInfo,), daemon=True)
    GLOBAL_STORE["mq_thread"] = t
    t.start()

    # 2. ע�� 100ms ��Ƶ��ʱ�ص�
    ContextInfo.run_time("check_and_process", "100nMilliSecond", "2020-01-01 00:00:00")

def check_and_process(ContextInfo):
    """QMT ���̣߳�ÿ 100ms �ص�һ�Σ�ȡ������ ? ��ӡ ? ����Ӧ�����"""
    if not getattr(ContextInfo, 'is_running', False):
        return

    # ����ȡ��ȫ�������������
    while not GLOBAL_REQ_QUEUE.empty():
        try:
            msg_recv = GLOBAL_REQ_QUEUE.get_nowait()
            
            #_handle_message(message)
            pkt = MsgPacket.decode(msg_recv)
            req_msg_id = pkt.msg_id().strip()
            # ��ӡ�յ���ԭʼ������Ϣ
            print(f"[RPC] <- {pkt.wire_to_string()}")
            
            code, msg, data = handle_trade_request(ContextInfo, pkt)
            
            msg_ans = build_answer(pkt, req_msg_id, code, msg, data)
            # ��ӡ���͵�Ӧ����Ϣ
            print(f"[RPC] -> {msg_ans.wire_to_string()}")
            
            _, msg_send = msg_ans.encode()

            # ��Ӧ����Ϣ��Ϣ����ȫ��Ӧ����У����� MQ �̷߳���
            GLOBAL_ANS_QUEUE.put(msg_send)
            
        except queue.Empty:
            break
        except Exception as e:
            print(f"[runtime �����쳣]: {e}")

def handlebar(ContextInfo):
    pass

def stop(ContextInfo):
    """���ֹͣ��ť�������� Socket ɱ�߳� + ��ն���"""
    print("\n==================================================")
    print("�յ�ָֹͣ���ʼ���� MQ �߳�...")
    print("==================================================")
    
    # 1. �ı�����״̬���λ
    ContextInfo.is_running = False

    # 2. ��ȫ�������ر� Socket����� channel.consume ����
    conn = GLOBAL_STORE.get("mq_conn")
    if conn:
        try:
            # ֻ�������Ӵ��ڴ�״̬��û�����ڹر�ʱ�ŵ��� close()
            if getattr(conn, 'is_open', False) and not getattr(conn, 'is_closed', True):
                conn.close()
        except Exception as e:
            # ��ʹ����Ҳ���Ժ��ԣ���ΪĿ����ǳ��׶Ͽ� Socket
            pass

    # 3. Join �ȴ��߳���������
    t = GLOBAL_STORE.get("mq_thread")
    if t and t.is_alive():
        t.join(timeout=1.0)
        print("MQ �߳���ȷ�����٣�")

    # 4. ��ղ�������
    while not GLOBAL_REQ_QUEUE.empty():
        try: GLOBAL_REQ_QUEUE.get_nowait()
        except: break
    while not GLOBAL_ANS_QUEUE.empty():
        try: GLOBAL_ANS_QUEUE.get_nowait()
        except: break

    print("������ϣ����Գɹ�ֹͣ��")












