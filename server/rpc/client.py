import asyncio
import json
import uuid
from datetime import datetime
from typing import Optional, Dict, Any

import aio_pika
from aio_pika import ExchangeType, Message

from msgpacket import MsgPacket, MSG_TYPE_REQUEST, MSG_TYPE_PUSH

from config import settings
from ws.manager import ws_manager

# 兼容旧引用：保留模块级常量名（值来自 config）
RABBITMQ_URL = settings.RABBITMQ_URL
EXCHANGE_NAME = settings.EXCHANGE_NAME
QUEUE_REQ = settings.QUEUE_REQ
QUEUE_REPLY = settings.QUEUE_REPLY
QUEUE_PUSH = settings.QUEUE_PUSH

# 推送类型 → WS channel
_PUSH_CHANNEL = {
    "ord_cfm": "order_update",
    "trd_cfm": "trade_update",
    "pos_cfm": "position_update",
    "ast_cfm": "asset_update",
}


def _clean_id(raw: str) -> str:
    """清理 msgid/func 字符串：去空白 + 去 null 填充。

    C 端 msg_header_t 字段是定长 char[]，Python 端读出来可能带 \\0 或空格，
    必须在两端用同一个清洗规则，否则会出现"看着一样但 dict 查不到"。
    """
    if not raw:
        return ""
    return raw.strip().rstrip("\x00").strip()


class RPClient:
    def __init__(self, url: str = RABBITMQ_URL):
        self.url = url
        self.conn: Optional[aio_pika.Connection] = None
        self.channel: Optional[aio_pika.Channel] = None
        self.exchange: Optional[aio_pika.Exchange] = None
        self.reply_queue: Optional[aio_pika.Queue] = None
        self.push_queue: Optional[aio_pika.Queue] = None
        self.pending: dict = {}  # msgid -> asyncio.Future

    async def connect(self):
        self.conn = await aio_pika.connect_robust(self.url)
        self.channel = await self.conn.channel()
        self.exchange = await self.channel.declare_exchange(
            EXCHANGE_NAME, ExchangeType.TOPIC, durable=True,
        )
        await self.channel.declare_queue(QUEUE_REQ, durable=True)
        self.reply_queue = await self.channel.declare_queue(QUEUE_REPLY, durable=True)
        self.push_queue = await self.channel.declare_queue(QUEUE_PUSH, durable=True)
        asyncio.ensure_future(self._listen_replies())
        asyncio.ensure_future(self._listen_pushs())
        print(
            f"[RPClient] connected, listening on reply={QUEUE_REPLY} push={QUEUE_PUSH}"
        )

    async def _listen_replies(self):
        """监听回复队列，通过 msgid 匹配 pending 的 future。

        协议要求柜台在应答包中回写请求的 msgid；若柜台未回写，
        这里的 "msg_id not in pending" 日志会指明收到的 msgid 是什么、
        以及当前等待的 msgid 列表，便于排查链路问题。
        """
        print("[RPClient] reply listener started")
        async with self.reply_queue.iterator() as qiter:
            async for msg in qiter:
                async with msg.process():
                    wire_data = msg.body
                    print(f"[RPClient] <<< reply wire_len={len(wire_data)}")
                    try:
                        pkt = MsgPacket.decode(wire_data)
                        msg_id = _clean_id(pkt.msg_id())
                        func = _clean_id(pkt.func())
                        try:
                            mt = chr(pkt.msg_type())
                        except Exception:
                            mt = "?"
                        print(
                            f"[RPClient] decoded func={func!r} type={mt!r} "
                            f"msg_id={msg_id!r} pending={list(self.pending.keys())}"
                        )
                        if msg_id and msg_id in self.pending:
                            future = self.pending.pop(msg_id)
                            if not future.done():
                                future.set_result(pkt)
                            print(
                                f"[RPClient] resolved msg_id={msg_id}, "
                                f"remaining_pending={len(self.pending)}"
                            )
                        else:
                            print(
                                f"[RPClient] WARN msg_id={msg_id!r} not in pending "
                                f"(have {len(self.pending)} pending, "
                                f"keys={list(self.pending.keys())})"
                            )
                    except Exception as e:
                        import traceback
                        print(f"[RPClient] decode/handle error: {type(e).__name__}: {e}")
                        traceback.print_exc()

    async def _listen_pushs(self):
        """监听 EvTrade.Test.Push 队列，把柜台主动推送转成 WS 消息。

        柜台不会回包给 ord_stk 的请求方（fire-and-forget），
        真正的成交通知通过 push 队列异步推送：
          - ord_cfm : 委托状态/成交通知（首次报单、状态变化）
          - trd_cfm : 成交回报
          - pos_cfm : 持仓变化（可选）
          - ast_cfm : 资金变化（可选）

        协议格式与 ANSWER 类似（func + headers + rows），但无 error_code 语义。
        """
        if not self.push_queue:
            print("[RPClient] push listener skipped: push_queue not declared")
            return
        print(f"[RPClient] push listener started, queue={QUEUE_PUSH}")
        async with self.push_queue.iterator() as qiter:
            async for msg in qiter:
                async with msg.process():
                    wire = msg.body
                    try:
                        pkt = MsgPacket.decode(wire)
                        func = _clean_id(pkt.func())
                        try:
                            mt = chr(pkt.msg_type())
                        except Exception:
                            mt = "?"
                        print(
                            f"[RPClient.push] <<< wire_len={len(wire)} "
                            f"func={func!r} type={mt!r}"
                        )

                        channel = _PUSH_CHANNEL.get(func)
                        if not channel:
                            print(
                                f"[RPClient.push] ignore unknown func={func!r}"
                            )
                            continue

                        rows = _parse_push_rows(pkt)
                        for row in rows:
                            payload = {
                                "type": func,
                                "channel": channel,
                                "ts": _clean_id(pkt.timestamp()) or "",
                                "data": row,
                            }
                            print(
                                f"[RPClient.push] broadcast → {channel}: "
                                f"{list(row.keys())[:6]}"
                            )
                            await ws_manager.broadcast(channel, payload)
                    except Exception as e:
                        import traceback
                        print(
                            f"[RPClient.push] decode/handle error: "
                            f"{type(e).__name__}: {e}"
                        )
                        traceback.print_exc()

    async def call(self, func: str, timeout: Optional[float] = None) -> MsgPacket:
        """发送 RPC 请求并等待应答。

        msgid 由 MsgPacket 构造时自动生成（UUID v4 hex，32 字符）。
        协议要求柜台在应答包中回写该 msgid，否则本调用会等到 timeout。
        """
        if timeout is None:
            timeout = settings.RPC_TIMEOUT
        pkt = MsgPacket(MSG_TYPE_REQUEST, "V1.0")
        pkt.set_func(func)
        pkt.finalize()

        msg_id = _clean_id(pkt.msg_id())
        if not msg_id:
            raise RuntimeError(
                "MsgPacket 未生成 msgid，请检查 msgpacket 库版本是否支持自动 UUID"
            )

        loop = asyncio.get_event_loop()
        future = loop.create_future()
        self.pending[msg_id] = future
        print(
            f"[RPClient.call] >>> func={func} msg_id={msg_id} "
            f"pending={len(self.pending)}"
        )

        _, wire_data = pkt.encode()
        await self.exchange.publish(
            Message(body=wire_data), routing_key=QUEUE_REQ
        )

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            # 超时清理 pending，避免内存泄漏 + 防止后续应答误匹配
            self.pending.pop(msg_id, None)
            print(
                f"[RPClient.call] TIMEOUT func={func} msg_id={msg_id} "
                f"after {timeout}s"
            )
            raise

    async def close(self):
        if self.conn:
            await self.conn.close()


_rpc_client: Optional[RPClient] = None


async def get_rpc_client() -> RPClient:
    global _rpc_client
    if _rpc_client is None:
        _rpc_client = RPClient()
        await _rpc_client.connect()
    return _rpc_client


async def close_rpc_client():
    global _rpc_client
    if _rpc_client:
        await _rpc_client.close()
        _rpc_client = None


# ================================================================
# 响应解析器
# ================================================================
def _parse_asset(pkt: MsgPacket) -> Dict[str, Any]:
    """解析资金查询结果"""
    result = {"cash": 0.0, "frozen_cash": 0.0, "market_value": 0.0, "total_asset": 0.0}

    for rs in range(1, pkt.result_set_count() + 1):
        if rs > 1:
            if not pkt.next_result_set():
                break

        pkt.reset_cursor()
        while pkt.fetch_next():
            cash = pkt.get_value_str("cash")
            frozen = pkt.get_value_str("frozen_cash")
            market = pkt.get_value_str("market_value")
            total = pkt.get_value_str("total_asset")

            if cash:
                result["cash"] = float(cash)
            if frozen:
                result["frozen_cash"] = float(frozen)
            if market:
                result["market_value"] = float(market)
            if total:
                result["total_asset"] = float(total)

    return result


def _parse_orders(pkt: MsgPacket) -> list:
    """解析委托查询结果"""
    orders = []

    for rs in range(1, pkt.result_set_count() + 1):
        if rs > 1:
            if not pkt.next_result_set():
                break

        pkt.reset_cursor()
        while pkt.fetch_next():
            order_id = pkt.get_value_str("order_id") or ""
            stock_code = pkt.get_value_str("stock_code") or ""
            price = pkt.get_value_str("price")
            volume = pkt.get_value_str("order_volume") or pkt.get_value_str("volume") or "0"
            traded_volume = pkt.get_value_str("traded_volume") or "0"
            traded_price = pkt.get_value_str("traded_price") or "0"
            status = pkt.get_value_str("order_status") or pkt.get_value_str("status") or ""
            order_type = pkt.get_value_str("order_type") or ""
            direction = pkt.get_value_str("direction") or ""
            order_time = pkt.get_value_str("order_time") or ""

            orders.append({
                "order_id": order_id,
                "stock_code": stock_code,
                "price": float(price) if price else 0.0,
                "volume": int(volume) if volume else 0,
                "traded_volume": int(traded_volume) if traded_volume else 0,
                "traded_price": float(traded_price) if traded_price else 0.0,
                "status": status,
                "order_type": order_type,
                "direction": direction,
                "order_time": order_time,
            })

    return orders


def _parse_trades(pkt: MsgPacket) -> list:
    """解析成交查询结果"""
    trades = []

    for rs in range(1, pkt.result_set_count() + 1):
        if rs > 1:
            if not pkt.next_result_set():
                break

        pkt.reset_cursor()
        while pkt.fetch_next():
            volume = pkt.get_value_str("volume") or pkt.get_value_str("traded_volume") or "0"
            price = pkt.get_value_str("price") or pkt.get_value_str("traded_price") or "0"

            trades.append({
                "trade_id": pkt.get_value_str("trade_id") or "",
                "order_id": pkt.get_value_str("order_id") or "",
                "stock_code": pkt.get_value_str("stock_code") or "",
                "direction": pkt.get_value_str("direction") or "",
                "volume": int(volume) if volume else 0,
                "price": float(price) if price else 0.0,
                "trade_time": pkt.get_value_str("trade_time") or "",
            })

    return trades


def _parse_push_rows(pkt: MsgPacket) -> list:
    """把 push 包里所有结果集的所有行原样取出，header 名 → 字符串值。

    与 _parse_* 不同：push 的字段名没有统一约定（ord_cfm / trd_cfm 各异），
    这里不强行类型转换，直接交由前端展示层处理。
    """
    rows: list = []
    headers = pkt.get_headers().split(",") if pkt.get_headers() else []
    headers = [h.strip() for h in headers if h.strip()]

    for rs in range(1, pkt.result_set_count() + 1):
        if rs > 1:
            if not pkt.next_result_set():
                break
        pkt.reset_cursor()
        while pkt.fetch_next():
            row = {}
            for h in headers:
                row[h] = pkt.get_value_str(h) or ""
            rows.append(row)
    return rows


# ================================================================
# 业务调用
# ================================================================
async def qry_asset() -> Dict[str, Any]:
    """查询资金 qry_ast"""
    client = await get_rpc_client()
    pkt = await client.call("qry_ast")
    return _parse_asset(pkt)


async def qry_orders() -> list:
    """查询委托 qry_ord"""
    client = await get_rpc_client()
    pkt = await client.call("qry_ord")
    return _parse_orders(pkt)


async def qry_trades() -> list:
    """查询成交 qry_mch"""
    client = await get_rpc_client()
    pkt = await client.call("qry_mch")
    return _parse_trades(pkt)


async def qry_positions() -> list:
    """查询持仓 qry_pos"""
    client = await get_rpc_client()
    pkt = await client.call("qry_pos")
    positions = []

    for rs in range(1, pkt.result_set_count() + 1):
        if rs > 1:
            if not pkt.next_result_set():
                break

        pkt.reset_cursor()
        while pkt.fetch_next():
            volume = pkt.get_value_str("volume") or "0"
            available = pkt.get_value_str("avl_amt") or pkt.get_value_str("available") or "0"
            cost = pkt.get_value_str("avg_price") or pkt.get_value_str("cost") or "0"
            market_value = pkt.get_value_str("market_value") or "0"

            positions.append({
                "stock_code": pkt.get_value_str("stock_code") or "",
                "stock_name": pkt.get_value_str("stock_name") or pkt.get_value_str("name") or "",
                "volume": int(volume) if volume else 0,
                "available": int(available) if available else 0,
                "cost": float(cost) if cost else 0.0,
                "market_value": float(market_value) if market_value else 0.0,
            })

    return positions


async def ord_stk(
    stock_code: str, volume: int, price_type: str, price: float, direction: str
) -> Dict[str, Any]:
    """下单 ord_stk（fire-and-forget）

    关键约束：
    1. msgid 由 MsgPacket 自动生成；柜台若回写应答包，可据此关联回报。
    2. XtQuant 的 ord_stk 本身是 fire-and-forget，broker 不直接回包；
       真正的成交通知通过 EvTrade.Test.Push 队列异步推送（ord_cfm / trd_cfm）。
    3. 这里发完立即返回临时 order_id，前端拿到后可轮询 GET /api/orders
       获取真实状态。
    """
    client = await get_rpc_client()

    pkt = MsgPacket(MSG_TYPE_REQUEST, "V1.0")
    pkt.set_func("ord_stk")
    pkt.set_headers(5, "stock_code,volume,price_type,price,direction")
    pkt.add_row()
    pkt.set_value("stock_code", stock_code)
    pkt.set_value("volume", str(volume))
    pkt.set_value("price_type", price_type)
    pkt.set_value("price", str(price))
    pkt.set_value("direction", direction)
    pkt.finalize()

    # 用独立 UUID 作为前端占位 order_id（与 msgid 解耦）
    temp_order_id = uuid.uuid4().hex[:8]

    _, wire_data = pkt.encode()
    await client.exchange.publish(
        Message(body=wire_data), routing_key=QUEUE_REQ
    )

    msg_id = _clean_id(pkt.msg_id())
    print(
        f"[ord_stk] published: stock_code={stock_code} volume={volume} "
        f"price={price} direction={direction} "
        f"temp_order_id={temp_order_id} msg_id={msg_id}"
    )
    return {"order_id": temp_order_id, "status": "pending"}


async def cancel_order(order_id: str) -> Dict[str, Any]:
    """撤单 cancel_ord（占位实现，未把 order_id 写入请求体）"""
    client = await get_rpc_client()
    pkt = await client.call("cancel_ord")
    return {"order_id": order_id, "status": "cancelled"}
