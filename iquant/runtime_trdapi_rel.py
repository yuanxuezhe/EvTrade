#coding:gbk
"""
==============================================================================
iQuant / QMT 策略极简模板：双队列 MQ 闭环通信与线程安全销毁
==============================================================================
流转路径：
1. [MQ 线程] channel.consume 订阅 MQ 请求队列 ? 放入 GLOBAL_REQ_QUEUE
2. [QMT 主线程] run_time(100ms) 取出 GLOBAL_REQ_QUEUE  打印  放入 GLOBAL_ANS_QUEUE
3. [MQ 线程] 监听到 GLOBAL_ANS_QUEUE 有数据 ? basic_publish 投递到 MQ 应答队列
4. [stop 函数] 主动关闭 Connection 打断 Socket 阻塞 ? 100% 物理销毁线程 ? 清空残留队列
"""

import queue
import threading
import pika
from msgpacket import MsgPacket, MSG_TYPE_ANSWER, MSG_TYPE_PUSH
from typing import Callable, Dict, List, Optional, Tuple

# ================================================================
# 1. 基础配置与全局队列/变量
# ================================================================
class Config:
    HOST = "192.168.10.2"
    PORT = 5672
    USER = "guest"
    PASS = "guest"
    VHOST = "/"
    
    EXCHANGE_NAME = "msgpacket.exchange"
    QUEUE_REQ = "EvTrade.Testgs.Req"
    QUEUE_REPLY = "EvTrade.Testgs.Reply"
    QUEUE_PUSH = "EvTrade.Testgs.Push"
    ACCOUNT_ID = '170000062910'
    # 410001265100   170000062910
config = Config()

ORDER_TYPE_STOCK = 1101
QUICK_TRADE_MODEL = 1
STRATEGY_NAME = 'EvTrade-Strategy'
# 全局线程安全队列
GLOBAL_REQ_QUEUE = queue.Queue()  # 请求队列 (MQ 线程  主线程)
GLOBAL_ANS_QUEUE = queue.Queue()  # 应答队列 (主线程   MQ 线程)
GLOBAL_PUSH_QUEUE = queue.Queue()  # 应答队列 (主线程   MQ 线程)
# 全局运行期句柄存储
GLOBAL_STORE = {
    "mq_conn": None,   # 存储 Connection，用于 stop() 物理打断 Socket 阻塞
    "mq_thread": None, # 存储 Thread 对象，用于 join 确认退出
}

# ================================================================
# Handler 注册请求接口
# ================================================================
#: Return: (code: str, msg: str, data: Optional[List[Dict]])
HandlerReturn = Tuple[str, str, Optional[List[Dict]]]
HandlerFunc = Callable[[MsgPacket], HandlerReturn]

_HANDLERS: Dict[str, HandlerFunc] = {}


def handler(func_name: str) -> Callable[[HandlerFunc], HandlerFunc]:
    """Handler 注册装饰器"""
    def decorator(func: HandlerFunc) -> HandlerFunc:
        _HANDLERS[func_name] = func
        return func
    return decorator


def handle_trade_request(context: ContextInfo, pkt: MsgPacket) -> HandlerReturn:
    """分发交易请求到对应 handler"""
    func = pkt.func().strip('\x00')

    handler = _HANDLERS.get(func)
    if handler is None:
        return "99999", f"unknown func: {func}", None
    try:
        return handler(context, pkt)
    except Exception as e:
        return "99999", str(e), None


# ================================================================
# 查询类 Handler
# ================================================================

@handler("qry_pos")
def _h_qry_pos(_context: ContextInfo, _pkt: MsgPacket) -> HandlerReturn:
    """查询持仓"""
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
    """查询订单"""
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
    """查询资产"""
    assets = get_trade_detail_data(config.ACCOUNT_ID, 'stock', 'account')
    #if asset is None:
    #    return "99999", "查询资产失败", None
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
    """查询成交"""
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
# 交易类 Handler
# ================================================================

@handler("ord_stk")
def _h_ord_stk(context: ContextInfo, pkt: MsgPacket) -> HandlerReturn:
    """异步下单处理句柄"""
    try:
        # 1. 批量提取并解析参数（结构清晰、类型明确）
        stock_code = pkt.get_value_str("stock_code")
        order_type = int(pkt.get_value_str("order_type"))
        price_type = int(pkt.get_value_str("price_type"))
        volume = float(pkt.get_value_str("volume"))
        price = float(pkt.get_value_str("price"))
        remark = pkt.get_value_str("remark")
    except (ValueError, TypeError) as e:
        return "99999", f"参数类型错误: {e}", []

    # 2. 基础业务校验（防止无效/危险报文）
    if volume <= 0:
        return "99998", f"下单数量[{volume}]必须大于0", []
    
    # 4. 执行下单指令
    passorder(
        order_type,           # 23: 买入 / 24: 卖出 等
        ORDER_TYPE_STOCK,     # 1101 订单类型
        config.ACCOUNT_ID,    # 资金账号
        stock_code,           # 标的代码
        price_type,           # 报价类型
        price,                # 报单价格
        volume,               # 报单数量
        STRATEGY_NAME,        # 策略名称
        QUICK_TRADE_MODEL,    # 快捷交易标识
        remark,               # 备注
        context               # 策略上下文
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
# 推送回包
# ================================================================

def order_callback(ContextInfo, orderInfo):
    """委托确认"""
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
    """成交回报"""
    push_event("trd_cfm", [{
        "traded_id": dealInfo.m_strTradeID,
        "stock_code": dealInfo.m_strInstrumentID + '.' + dealInfo.m_strExchangeID,
        "traded_volume": dealInfo.m_nVolume,
        "traded_price": dealInfo.m_dPrice,
        "strategy_name": '',
        "remark": dealInfo.m_strRemark,
    }])
    
def position_callback(ContextInfo, positonInfo):
    """ 持仓推送 """
    push_event("pos_push", [{
        "stock_code": positonInfo.m_strInstrumentID + '.' + positonInfo.m_strExchangeID,
        "last_vol": positonInfo.m_nYesterdayVolume,
        "volume": positonInfo.m_nVolume,
        "avl_amt": positonInfo.m_nCanUseVolume,
        "avg_price": positonInfo.m_dOpenPrice,
    }])

# ================================================================
# 应答组包
# ================================================================
def build_answer(pkt: MsgPacket, req_msg_id: str,
                 code: str, msg: str, data: List[Dict]) -> MsgPacket:
    """按 msgpacket 格式组应答包
    code != 0: RS1={code,msg}
    code == 0: RS1={code,msg} + RS2=data表
    """
    ans = MsgPacket(MSG_TYPE_ANSWER, pkt.version())
    ans.set_msg_id(req_msg_id)
    ans.set_func(pkt.func().strip('\x00'))

    # RS1: code + msg
    ans.set_headers(2, "code,msg")
    ans.add_row()
    ans.set_value("code", code)
    ans.set_value("msg", msg)

    # RS2: 数据表 (code==0 且有数据时才有)
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
    """线程安全地推送事件到 RabbitMQ"""
    _mq_publish(func, data)

def _mq_publish(func: str, data: List[Dict]) -> None:
    """推送消息: func=功能号, data=RS1数据表"""
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
        # 将应答消息消息塞入全局应答队列，交由 MQ 线程发回
        GLOBAL_PUSH_QUEUE.put(msg_push)
    except Exception as e:
        print(f"[Push] 失败 {func}: {e}", flush=True)
        
# ================================================================
# 2. MQ 独立线程（订阅请求 + 监听应答队列发送）
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

        # 挂载连接对象，供 stop() 随时安全打断
        GLOBAL_STORE["mq_conn"] = conn

        # 声明 Exchange 和 Queues
        channel.exchange_declare(exchange=config.EXCHANGE_NAME, exchange_type='topic', durable=True)
        channel.queue_declare(queue=config.QUEUE_REQ, durable=True)
        channel.queue_bind(queue=config.QUEUE_REQ, exchange=config.EXCHANGE_NAME, routing_key=config.QUEUE_REQ)
        channel.queue_declare(queue=config.QUEUE_REPLY, durable=True)

        channel.basic_qos(prefetch_count=1)
        print("[MQ 线程] 订阅成功，进入收发监听通道...")

        def process_send_queue():
            """刷出 GLOBAL_ANS_QUEUE 中的待发数据并投递到 RabbitMQ"""
            while not GLOBAL_ANS_QUEUE.empty():
                try:
                    msg_bytes = GLOBAL_ANS_QUEUE.get_nowait()
                    if channel.is_open:
                        channel.basic_publish(
                            exchange='',  # 直接投递到指定名称的应答队列
                            routing_key=config.QUEUE_REPLY,
                            body=msg_bytes
                        )
                        #print(f"[send]: {msg_bytes.wire_to_string()}")
                except queue.Empty:
                    break
                except Exception as e:
                    print(f"[MQ 发送异常]: {e}")
                    
            """刷出 GLOBAL_PUSH_QUEUE 中的待发数据并投递到 RabbitMQ"""
            while not GLOBAL_PUSH_QUEUE.empty():
                try:
                    msg_bytes = GLOBAL_PUSH_QUEUE.get_nowait()
                    if channel.is_open:
                        channel.basic_publish(
                            exchange='',  # 直接投递到指定名称的应答队列
                            routing_key=config.QUEUE_PUSH,
                            body=msg_bytes
                        )
                        #print(f"[send]: {msg_bytes.wire_to_string()}")
                except queue.Empty:
                    break
                except Exception as e:
                    print(f"[MQ 发送异常]: {e}")
        
        # 使用 consume + inactivity_timeout 实现订阅接收与应答发送的交替驱动
        for message_metadata, properties, body in channel.consume(queue=config.QUEUE_REQ, inactivity_timeout=0.2):
            # 停止信号判定
            if not getattr(ContextInfo, 'is_running', False):
                print("[MQ 线程] 收到策略停止信号，准备退出循环...")
                break

            # A. 优先将全局应答队列中的数据刷入 MQ
            process_send_queue()

            # B. 订阅收到请求报文，塞入全局请求队列
            if body is not None:
                GLOBAL_REQ_QUEUE.put(body)
                channel.basic_ack(delivery_tag=message_metadata.delivery_tag)

    except pika.exceptions.AMQPConnectionError:
        print("[MQ 线程] Socket 连接已被主程序主动关停，线程打断成功。")
    except Exception as e:
        print(f"[MQ 线程异常]: {e}")
    finally:
        # 注意：这里只清空句柄，不要重复调用 conn.close()
        # 因为 stop() 中已经主动 close 过了，或者连接因异常本身已关闭
        GLOBAL_STORE["mq_conn"] = None
        print("[MQ 线程] 已完全退出并销毁！")

# ================================================================
# 3. QMT 策略生命周期 & runtime 定时器
# ================================================================
def init(ContextInfo):
    print("==================================================")
    print("iQuant 双队列极简收发引擎 启动...")
    print("==================================================")
    ContextInfo.is_running = True
    ContextInfo.set_account(config.ACCOUNT_ID)
    # 1. 启动独立 MQ 线程
    t = threading.Thread(target=rabbitmq_worker, args=(ContextInfo,), daemon=True)
    GLOBAL_STORE["mq_thread"] = t
    t.start()

    # 2. 注册 100ms 高频定时回调
    ContextInfo.run_time("check_and_process", "100nMilliSecond", "2020-01-01 00:00:00")

def check_and_process(ContextInfo):
    """QMT 主线程：每 100ms 回调一次，取出请求 ? 打印 ? 塞回应答队列"""
    if not getattr(ContextInfo, 'is_running', False):
        return

    # 批量取出全局请求队列数据
    while not GLOBAL_REQ_QUEUE.empty():
        try:
            msg_recv = GLOBAL_REQ_QUEUE.get_nowait()
            
            #_handle_message(message)
            pkt = MsgPacket.decode(msg_recv)
            req_msg_id = pkt.msg_id().strip()
            # 打印收到的原始请求消息
            print(f"[RPC] <- {pkt.wire_to_string()}")
            
            code, msg, data = handle_trade_request(ContextInfo, pkt)
            
            msg_ans = build_answer(pkt, req_msg_id, code, msg, data)
            # 打印发送的应答消息
            print(f"[RPC] -> {msg_ans.wire_to_string()}")
            
            _, msg_send = msg_ans.encode()

            # 将应答消息消息塞入全局应答队列，交由 MQ 线程发回
            GLOBAL_ANS_QUEUE.put(msg_send)
            
        except queue.Empty:
            break
        except Exception as e:
            print(f"[runtime 处理异常]: {e}")

def handlebar(ContextInfo):
    pass

def stop(ContextInfo):
    """点击停止按钮：物理关 Socket 杀线程 + 清空队列"""
    print("\n==================================================")
    print("收到停止指令，开始销毁 MQ 线程...")
    print("==================================================")
    
    # 1. 改变运行状态标记位
    ContextInfo.is_running = False

    # 2. 安全地物理关闭 Socket，打断 channel.consume 阻塞
    conn = GLOBAL_STORE.get("mq_conn")
    if conn:
        try:
            # 只有在连接处于打开状态且没有正在关闭时才调用 close()
            if getattr(conn, 'is_open', False) and not getattr(conn, 'is_closed', True):
                conn.close()
        except Exception as e:
            # 即使报错也可以忽略，因为目标就是彻底断开 Socket
            pass

    # 3. Join 等待线程物理结束
    t = GLOBAL_STORE.get("mq_thread")
    if t and t.is_alive():
        t.join(timeout=1.0)
        print("MQ 线程已确认销毁！")

    # 4. 清空残留队列
    while not GLOBAL_REQ_QUEUE.empty():
        try: GLOBAL_REQ_QUEUE.get_nowait()
        except: break
    while not GLOBAL_ANS_QUEUE.empty():
        try: GLOBAL_ANS_QUEUE.get_nowait()
        except: break

    print("清理完毕，策略成功停止。")











