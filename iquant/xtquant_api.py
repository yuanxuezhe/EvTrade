#!/usr/bin/env python3
# -*- coding: gbk -*-
"""
XtQuant API + msgpacket RPC Server

锟斤拷锟斤拷 QMT 锟斤拷锟阶接口猴拷 RabbitMQ RPC锟斤拷支锟街ｏ拷
1. 锟斤拷 RabbitMQ 锟斤拷锟秸斤拷锟斤拷锟斤拷锟襟（诧拷植锟?/锟斤拷锟斤拷/锟绞诧拷锟饺ｏ拷锟斤拷锟斤拷锟斤拷锟襟返伙拷应锟斤拷
2. 锟斤拷 QMT 锟截碉拷锟铰硷拷锟斤拷锟缴斤拷/委锟斤拷/锟斤拷锟斤拷锟斤拷锟酵碉拷 RabbitMQ

锟矫凤拷:
    python xtquant_api.py
"""

import asyncio
import random
import threading
import time
from datetime import datetime
from queue import Empty, Queue
from typing import Callable, Dict, List, Optional, Tuple

import aio_pika
from aio_pika import ExchangeType

from msgpacket import MsgPacket, MSG_TYPE_ANSWER, MSG_TYPE_PUSH
from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
from xtquant.xttype import StockAccount
from xtquant import xtconstant


# ================================================================
# 锟斤拷锟斤拷
# ================================================================

class Config:
    """全锟斤拷锟斤拷锟斤拷"""
    RABBITMQ_URL = "amqp://192.168.10.2:5672/"
    EXCHANGE_NAME = "msgpacket.exchange"
    QUEUE_REQ = "EvTrade.Test.Req"
    QUEUE_REPLY = "EvTrade.Test.Reply"
    QUEUE_PUSH = "EvTrade.Test.Push"
    ACCOUNT_PATH = r"D:\software\trade\iQuant\userdata"
    ACCOUNT_ID = "410001265100" 
    #"410001265100   170000062910"


config = Config()


# ================================================================
# 全锟斤拷状态
# ================================================================

class GlobalState:
    """全锟街癸拷锟斤拷状态"""
    def __init__(self):
        self.xt_trader = None
        self.xt_acc = None
        self.event_queue = Queue()
        self.loop = None
        self.shutdown_event = None
        # RabbitMQ 锟斤拷锟斤拷锟斤拷
        self.mq_conn = None
        self.mq_channel = None
        self.mq_exchange = None


state = GlobalState()


# ================================================================
# Handler 注锟斤拷
# ================================================================
#: Return: (code: str, msg: str, data: Optional[List[Dict]])
HandlerReturn = Tuple[str, str, Optional[List[Dict]]]
HandlerFunc = Callable[[MsgPacket], HandlerReturn]

_HANDLERS: Dict[str, HandlerFunc] = {}


def handler(func_name: str) -> Callable[[HandlerFunc], HandlerFunc]:
    """Handler 注锟斤拷装锟斤拷锟斤拷"""
    def decorator(func: HandlerFunc) -> HandlerFunc:
        _HANDLERS[func_name] = func
        return func
    return decorator


def handle_trade_request(pkt: MsgPacket) -> HandlerReturn:
    """锟街凤拷锟斤拷锟斤拷锟斤拷锟襟到讹拷应 handler"""
    func = pkt.func().strip('\x00')
    if state.xt_trader is None:
        return "99999", "锟斤拷锟阶接匡拷未锟斤拷锟斤拷", None
    handler = _HANDLERS.get(func)
    if handler is None:
        return "99999", f"unknown func: {func}", None
    try:
        return handler(pkt)
    except Exception as e:
        return "99999", str(e), None


# ================================================================
# 锟斤拷询锟斤拷 Handler
# ================================================================

@handler("qry_pos")
def _h_qry_pos(_pkt: MsgPacket) -> HandlerReturn:
    """锟斤拷询锟街诧拷"""
    positions = state.xt_trader.query_stock_positions(state.xt_acc)
    return "00000", "ok", [{
        "stock_code": pos.stock_code,
        "volume": pos.volume,
        "avl_amt": pos.can_use_volume,
        "avg_price": pos.open_price,
        "market_value": pos.market_value,
    } for pos in positions]


@handler("qry_ord")
def _h_qry_ord(_pkt: MsgPacket) -> HandlerReturn:
    """锟斤拷询锟斤拷锟斤拷"""
    orders = state.xt_trader.query_stock_orders(state.xt_acc)
    return "00000", "ok", [{
        "order_id": order.order_sysid,
        "stock_code": order.stock_code,
        "price": order.price,
        "order_volume": order.order_volume,
        "traded_volume": order.traded_volume,
        "traded_price": order.traded_price,
        "order_status": order.order_status,
        "status_msg": order.status_msg,
        "strategy_name": order.strategy_name,
        "order_remark": order.order_remark,
        "order_time": order.order_time,
    } for order in orders]


@handler("qry_ast")
def _h_qry_ast(_pkt: MsgPacket) -> HandlerReturn:
    """锟斤拷询锟绞诧拷"""
    asset = state.xt_trader.query_stock_asset(state.xt_acc)
    if asset is None:
        return "99999", "锟斤拷询锟绞诧拷失锟斤拷", None
    return "00000", "ok", [{
        "account_id": asset.account_id,
        "cash": asset.cash,
        "frozen_cash": asset.frozen_cash,
        "market_value": asset.market_value,
        "total_asset": asset.total_asset,
    }]


@handler("qry_mch")
def _h_qry_mch(_pkt: MsgPacket) -> HandlerReturn:
    """锟斤拷询锟缴斤拷"""
    trades = state.xt_trader.query_stock_trades(state.xt_acc)
    return "00000", "ok", [{
        "order_id": trade.order_sysid,
        "traded_id": trade.traded_id,
        "stock_code": trade.stock_code,
        "traded_volume": trade.traded_volume,
        "traded_price": trade.traded_price,
        "traded_amount": trade.traded_amount,
        "strategy_name": trade.strategy_name,
        "order_remark": trade.order_remark,
        "traded_time": trade.traded_time,
    } for trade in trades]


# ================================================================
# 锟斤拷锟斤拷锟斤拷 Handler
# ================================================================

@handler("ord_stk")
def _h_ord_stk(pkt: MsgPacket) -> HandlerReturn:
    """锟届步锟铰碉拷"""
    stock_code = pkt.get_value_str("stock_code")
    volume = int(pkt.get_value_str("volume"))
    price_type_str = pkt.get_value_str("price_type")
    price = float(pkt.get_value_str("price"))
    direction_str = pkt.get_value_str("direction")
    remark = pkt.get_value_str("remark")

# v__: 浠锋牸绫诲瀷涓? xtconstant 鏋跺彴鍗忚?? 1:1 瀵归綈
    #   "0" -> FIX_PRICE                  (闄愪环 / 鎸囧畾浠?)
    #   "1" -> LATEST_PRICE               (鏈?鏂颁环)
    #   "2" -> MARKET_PEER_PRICE_FIRST    (甯備环 / 瀵规墜鏂规渶浼樹环, 鍚冩。 1)
    price_type_map = {
        "0": xtconstant.FIX_PRICE,
        "1": xtconstant.LATEST_PRICE,
        "2": xtconstant.MARKET_PEER_PRICE_FIRST,
    }
    price_type = price_type_map.get(price_type_str, xtconstant.LATEST_PRICE)
    direction = xtconstant.STOCK_BUY if direction_str == "BUY" else xtconstant.STOCK_SELL

    seq = state.xt_trader.order_stock_async(
        state.xt_acc, stock_code, direction, volume,
        price_type, price, "xtquant_api", remark,
    )
    return "00000", "ok", [{"seq": seq}]


@handler("cxl_ord")
def _h_cxl_ord(pkt: MsgPacket) -> HandlerReturn:
    """cancel order (xtquant API takes only acc + order_id, no market/stock_code)"""
    order_id = pkt.get_value_str("order_id")
    result = state.xt_trader.cancel_order_stock_async(state.xt_acc, order_id)
    return "00000", "ok", [{"result": result}]


# ================================================================
# 应锟斤拷锟斤拷锟?
# ================================================================
def build_answer(pkt: MsgPacket, req_msg_id: str,
                 code: str, msg: str, data: List[Dict]) -> MsgPacket:
    """锟斤拷 msgpacket 锟斤拷式锟斤拷应锟斤拷锟?
    code != 0: RS1={code,msg}
    code == 0: RS1={code,msg} + RS2=data锟斤拷
    """
    ts = datetime.now().strftime('%Y%m%d%H%M%S') + '000'
    ans = MsgPacket(MSG_TYPE_ANSWER, pkt.version())
    ans.set_msg_id(req_msg_id)
    ans.set_timestamp(ts)
    ans.set_func(pkt.func().strip('\x00'))

    # RS1: code + msg
    ans.set_headers(2, "code,msg")
    ans.add_row()
    ans.set_value("code", code)
    ans.set_value("msg", msg)

    # RS2: 锟斤拷锟捷憋拷 (code==0 锟斤拷锟斤拷锟斤拷锟斤拷时锟斤拷锟斤拷)
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

# ================================================================
# XtQuantTrader 锟截碉拷 锟斤拷 RabbitMQ 锟斤拷锟斤拷
# ================================================================

class MyXtQuantTraderCallback(XtQuantTraderCallback):
    """QMT 锟斤拷锟阶回碉拷锟斤拷转锟铰硷拷锟斤拷 RabbitMQ"""

    def on_disconnected(self) -> None:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] [Cb] 锟斤拷锟接断匡拷锟斤拷锟斤拷锟斤拷锟斤拷", flush=True)
        state.xt_trader = None
        state.event_queue.put(("disconnected", None))

    def on_stock_order(self, order) -> None:
        """濮旀墭纭?璁?"""
        push_event("ord_cfm", [{
            "order_id": order.order_sysid,
            "stock_code": order.stock_code,
            "order_status": order.order_status,
            "order_volume": order.order_volume,
            "traded_volume": order.traded_volume,
            "price": order.price,
            "traded_price": order.traded_price,
            "strategy_name": order.strategy_name,
            "remark": order.order_remark,
            "order_time": order.order_time,
        }])

    def on_stock_trade(self, trade) -> None:
        """鎴愪氦鍥炴姤"""
        push_event("trd_cfm", [{
            "traded_id": trade.traded_id,
            "stock_code": trade.stock_code,
            "traded_volume": trade.traded_volume,
            "traded_price": trade.traded_price,
            "account_id": trade.account_id,
            "strategy_name": trade.strategy_name,
            "remark": trade.order_remark,
        }])

    # v118: 鎸佷粨鍙樺寲鎺ㄩ?佸洖璋? 鈥? broker 姣忔?℃寔浠撳彉鍖栭兘浼氳Е鍙?
    #   璁捐??: pos_push 鏄? v118 鍚庣殑鍞?涓?鎸佷粨鏁版嵁婧?
    #         trd_cfm 涓嶅啀澶勭悊鎸佷粨 (浠呭啓 trades + orders)
    #         reconcile 涓嶅啀瑕嗙洊鎸佷粨 (浠呭垵濮嬪寲鏃剁敤 qry_positions 鍚屾??)
    def on_stock_position(self, position) -> None:
        """鎸佷粨鍙樺寲鎺ㄩ?? (xtquant 鍗忚??)"""
        try:
            # 鍏煎?? broker 涓嶅悓鐗堟湰瀛楁?靛悕 鈥? 灏藉姏瑙ｆ瀽
            code = getattr(position, 'stock_code', None) or getattr(position, 'm_strInstrumentID', '')
            exchange = getattr(position, 'exchange_id', None) or getattr(position, 'm_strExchangeID', '')
            if exchange and '.' not in code:
                code = f"{code}.{exchange}"
            push_event("pos_push", [{
                "stock_code": code,
                "last_vol": int(getattr(position, 'yesterday_volume', 0) or getattr(position, 'm_nYesterdayVolume', 0)),
                "vol": int(getattr(position, 'volume', 0) or getattr(position, 'm_nVolume', 0)),
                "avl_vol": int(getattr(position, 'can_use_volume', 0) or getattr(position, 'm_nCanUseVolume', 0)),
                "avg_price": float(getattr(position, 'open_price', 0) or getattr(position, 'm_dOpenPrice', 0)),
            }])
        except Exception as e:
            print(f"[Cb] pos_push 瑙ｆ瀽澶辫触: {e}", flush=True)

    def on_order_error(self, order_error) -> None:
        """涓嬪崟澶辫触"""
        push_event("ord_err", [{
            "order_id": order_error.order_id,
            "error_msg": order_error.error_msg,
        }])

    def on_cancel_error(self, cancel_error) -> None:
        """鎾ゅ崟澶辫触"""
        push_event("cxl_err", [{
            "order_id": cancel_error.order_id,
            "error_msg": cancel_error.error_msg,
        }])

    def on_order_stock_async_response(self, response) -> None:
        """寮傛?ヤ笅鍗曞搷搴?"""
        push_event("ord_ack", [{
            "seq": response.seq,
            "order_id": response.order_sysid,
        }])

    def on_account_status(self, status) -> None:
        """璐﹀彿鐘舵??"""
        push_event("acc_sts", [{
            "account_id": status.account_id,
            "status": status.status,
        }])


# ================================================================
# RabbitMQ 锟斤拷锟斤拷
# ================================================================

def push_event(func: str, data: List[Dict]) -> None:
    """锟竭程帮拷全锟斤拷锟斤拷锟斤拷锟铰硷拷锟斤拷 RabbitMQ"""
    if state.loop is None or state.loop.is_closed():
        return
    asyncio.run_coroutine_threadsafe(_mq_publish(func, data), state.loop)


async def _mq_publish(func: str, data: List[Dict]) -> None:
    """锟斤拷锟斤拷锟斤拷息: func=锟斤拷锟杰猴拷, data=RS1锟斤拷锟捷憋拷"""
    if state.mq_exchange is None:
        return
    try:
        pkt = MsgPacket(MSG_TYPE_PUSH)
        pkt.set_func(func)
        pkt.set_timestamp(datetime.now().strftime('%Y%m%d%H%M%S%f')[:-3])

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
        _, wire = pkt.encode()
        await state.mq_exchange.publish(aio_pika.Message(body=wire), routing_key=config.QUEUE_PUSH)
    except Exception as e:
        print(f"[Push] 失锟斤拷 {func}: {e}", flush=True)


# ================================================================
# XtQuantTrader 锟斤拷锟接癸拷锟斤拷
# ================================================================

def create_trader(session_id: int) -> Optional[XtQuantTrader]:
    """锟斤拷锟斤拷锟斤拷锟斤拷锟接斤拷锟阶客伙拷锟斤拷"""
    try:
        callback = MyXtQuantTraderCallback()
        trader = XtQuantTrader(config.ACCOUNT_PATH, session_id, callback=callback)
        trader.start()
        result = trader.connect()
        if result == 0:
            trader.subscribe(state.xt_acc)
            # v118: subscribe_position (xtquant protocol support) — triggers on_stock_position push
            #   old broker may only subscribe orders/trades, now also subscribe positions
            #   if xtquant version does not support, AttributeError is caught
            try:
                if hasattr(trader, 'subscribe_position'):
                    trader.subscribe_position(state.xt_acc)
                    print("[Trader] subscribed position_update via subscribe_position", flush=True)
            except Exception as _e:
                print(f"[Trader] subscribe_position skipped (protocol unsupported): {_e}", flush=True)
            print(f"[Trader] connected, session_id={session_id}", flush=True)
            return trader
        print(f"[Trader] 锟斤拷锟斤拷失锟斤拷, session_id={session_id}, result={result}", flush=True)
        return None
    except Exception as e:
        print(f"[Trader] 锟届常, session_id={session_id}: {e}", flush=True)
        return None


def try_connect() -> Optional[XtQuantTrader]:
    """锟斤拷锟斤拷锟斤拷锟接ｏ拷使锟斤拷锟斤拷锟? session_id"""
    session_ids = list(range(100, 130))
    random.shuffle(session_ids)
    for sid in session_ids:
        trader = create_trader(sid)
        if trader:
            return trader
        print(f"[Trader] session_id={sid} 失锟杰ｏ拷锟斤拷锟斤拷锟斤拷一锟斤拷...", flush=True)
        time.sleep(0.5)
    print("[Trader] 锟斤拷锟斤拷 session_id 锟斤拷锟斤拷锟皆猴拷锟斤拷失锟斤拷", flush=True)
    return None


def ensure_connected() -> bool:
    """确锟斤拷锟斤拷锟阶接匡拷锟斤拷锟斤拷锟斤拷"""
    if state.xt_trader is None:
        state.xt_trader = try_connect()
    return state.xt_trader is not None


# ================================================================
# RabbitMQ RPC Server
# ================================================================

async def rpc_server() -> None:
    """RPC 锟斤拷锟斤拷锟斤拷锟斤拷锟斤拷锟斤拷锟斤拷锟襟、碉拷锟斤拷 handler锟斤拷锟斤拷锟斤拷应锟斤拷"""
    print(f"[RPC] Connecting to {config.RABBITMQ_URL}", flush=True)
    state.mq_conn = await aio_pika.connect_robust(config.RABBITMQ_URL)
    state.mq_channel = await state.mq_conn.channel()
    await state.mq_channel.set_qos(prefetch_count=1)

    state.mq_exchange = await state.mq_channel.declare_exchange(
        config.EXCHANGE_NAME, ExchangeType.TOPIC, durable=True,
    )

    req_queue = await state.mq_channel.declare_queue(config.QUEUE_REQ, durable=True)
    await req_queue.bind(state.mq_exchange, routing_key=config.QUEUE_REQ)
    print(f"[RPC] Connected, Listening on [{config.QUEUE_REQ}]", flush=True)

    # 锟斤拷锟斤拷锟斤拷锟斤拷锟斤拷锟酵讹拷锟叫ｏ拷锟斤拷锟酵伙拷锟斤拷锟斤拷锟斤拷锟斤拷锟斤拷锟铰硷拷
    push_queue = await state.mq_channel.declare_queue(config.QUEUE_PUSH, durable=True)
    await push_queue.bind(state.mq_exchange, routing_key=config.QUEUE_PUSH)
    print(f"[RPC] Push queue ready: [{config.QUEUE_PUSH}]", flush=True)

    await asyncio.sleep(0.3)

    async with req_queue.iterator() as qiter:
        async for message in qiter:
            if state.shutdown_event.is_set():
                break

            async with message.process():
                await _handle_message(message)


async def _handle_message(message) -> None:
    """锟斤拷锟斤拷锟斤拷锟斤拷 RPC 锟斤拷锟斤拷"""
    try:
        pkt = MsgPacket.decode(message.body)
    except Exception as e:
        print(f"[RPC] Decode error: {e}", flush=True)
        return

    req_msg_id = pkt.msg_id().strip()
    print(f"[RPC] <- {pkt.wire_to_string()}", flush=True)

    code, msg, data = handle_trade_request(pkt)

    ans = build_answer(pkt, req_msg_id, code, msg, data)
    print(f"[RPC] -> {ans.wire_to_string()}", flush=True)
    _, ans_wire = ans.encode()

    await state.mq_channel.default_exchange.publish(
        aio_pika.Message(body=ans_wire),
        routing_key=config.QUEUE_REPLY,
    )


# ================================================================
# 锟斤拷锟斤拷锟斤拷
# ================================================================

def event_loop_thread() -> None:
    """锟斤拷锟斤拷 asyncio 锟铰硷拷循锟斤拷锟斤拷锟竭筹拷"""
    state.loop = asyncio.new_event_loop()
    asyncio.set_event_loop(state.loop)
    state.shutdown_event = asyncio.Event()
    try:
        state.loop.run_until_complete(rpc_server())
    except asyncio.CancelledError:
        print("[Main] RPC server cancelled", flush=True)
    finally:
        print("[Main] Event loop exiting", flush=True)
        state.loop.close()


def main() -> None:
    """锟斤拷锟斤拷锟?"""
    state.xt_acc = StockAccount(config.ACCOUNT_ID)
    print(f"[Main] 锟剿伙拷: {config.ACCOUNT_ID}", flush=True)

    if not ensure_connected():
        print("[Main] 锟斤拷始锟斤拷锟斤拷失锟杰ｏ拷RPC server 锟皆伙拷锟斤拷锟斤拷", flush=True)

    threading.Thread(target=event_loop_thread, daemon=True).start()
    print("[Main] RPC server 锟竭筹拷锟斤拷锟斤拷锟斤拷", flush=True)
    
    # 锟斤拷锟斤拷锟斤拷锟竭筹拷锟剿筹拷
    state.xt_trader.run_forever()

if __name__ == "__main__":
    print("=" * 60)
    print("XtQuant API + msgpacket RPC Server")
    print("=" * 60)
    main()









