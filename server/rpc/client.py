import asyncio
import json
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


def _wire_dump(pkt: "MsgPacket") -> str:
    """用 msgpacket 自带的 wire_to_string 抓报文字符串视图，便于排查。

    返回空串时上层不打印，避免噪音。
    """
    try:
        s = pkt.wire_to_string()
    except Exception as e:
        return f"<wire_to_string error: {type(e).__name__}: {e}>"
    return s or ""


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
                        reply_dump = _wire_dump(pkt)
                        if reply_dump:
                            print(f"[RPClient] <<< wire:\n{reply_dump}")
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

    async def call(
        self,
        func: str,
        timeout: Optional[float] = None,
        headers: Optional[str] = None,
        values: Optional[Dict[str, Any]] = None,
    ) -> MsgPacket:
        """发送 RPC 请求并等待应答。

        msgid 由 MsgPacket 构造时自动生成（UUID v4 hex，32 字符）。
        协议要求柜台在应答包中回写该 msgid，否则本调用会等到 timeout。

        可选参数：
          headers: 逗号分隔的字段名（如 "stock_code,volume,price"），用于带请求体的调用。
          values:  字段名 → 字符串值的 dict；会在 headers 设置后写入第一行。
        """
        if timeout is None:
            timeout = settings.RPC_TIMEOUT
        pkt = MsgPacket(MSG_TYPE_REQUEST, "V1.0")
        pkt.set_func(func)
        if headers:
            names = [h.strip() for h in headers.split(",") if h.strip()]
            pkt.set_headers(len(names), ",".join(names))
            if values:
                pkt.add_row()
                for name in names:
                    if name in values:
                        pkt.set_value(name, str(values[name]))
        pkt.finalize()

        msg_id = _clean_id(pkt.msg_id())
        if not msg_id:
            raise RuntimeError(
                "MsgPacket 未生成 msgid，请检查 msgpacket 库版本是否支持自动 UUID"
            )

        loop = asyncio.get_event_loop()
        future = loop.create_future()
        self.pending[msg_id] = future

        _, wire_data = pkt.encode()
        print(
            f"[RPClient.call] >>> func={func} msg_id={msg_id} "
            f"pending={len(self.pending)} wire_len={len(wire_data)}"
        )
        req_dump = _wire_dump(pkt)
        if req_dump:
            print(f"[RPClient.call] >>> wire:\n{req_dump}")

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
#
# 应答协议（柜台返回）：
#   - 第 1 结果集：固定两字段 code / msg，1 行
#       * code == 0 表示成功；其他值表示业务错误
#       * msg  为人类可读的错误描述
#   - 第 2 结果集：业务数据，0..N 行（仅当 code == 0 时才有意义）
#
# 所有 _parse_* 解析器统一返回 {"code": int, "msg": str, "list": list}：
#   - code != 0 时 list 直接为空，不读第二结果集
#   - code == 0 时按各业务字段映射规则解析第二结果集，list 为业务对象数组


def _select_rs(pkt: MsgPacket, rs: int) -> bool:
    """安全切换到第 rs 个结果集（1-based）。

    优先使用 select_result_set(rs)；某些 msgpacket 版本在该 API 异常时，
    回退到 reset → next_result_set 的链式定位。返回是否成功。
    """
    try:
        ok = pkt.select_result_set(rs)
        if ok is False:
            return False
        # 部分实现 select_result_set 不返回 bool，按当前 rs 校验
        try:
            return pkt.result_set() == rs
        except Exception:
            return True
    except Exception:
        pass
    # fallback
    try:
        pkt.select_result_set(1)
    except Exception:
        pass
    cur = 1
    while cur < rs:
        if not pkt.next_result_set():
            return False
        cur += 1
    return True


def _parse_code_msg(pkt: MsgPacket) -> tuple:
    """读取第 1 结果集中的 code/msg。失败时返回 (-1, str)。"""
    if pkt.result_set_count() < 1:
        return -1, "empty packet"
    if not _select_rs(pkt, 1):
        return -1, "missing result set #1"
    pkt.reset_cursor()
    if not pkt.fetch_next():
        return -1, "missing code row"
    raw_code = (pkt.get_value_str("code") or "").strip()
    raw_msg = (pkt.get_value_str("msg") or "").strip()
    try:
        code = int(raw_code) if raw_code else -1
    except ValueError:
        code = -1
    return code, raw_msg


def _iter_rows(pkt: MsgPacket, rs: int) -> list:
    """把第 rs 个结果集的所有行按 headers 解析为 dict 数组。

    与 _parse_push_rows 思路一致：不做类型转换，由调用方按业务再做映射。
    若第 rs 个结果集不存在，返回空数组。
    """
    if pkt.result_set_count() < rs:
        return []
    if not _select_rs(pkt, rs):
        return []
    headers_str = pkt.get_headers() or ""
    headers = [h.strip() for h in headers_str.split(",") if h.strip()]
    rows: list = []
    pkt.reset_cursor()
    while pkt.fetch_next():
        rows.append({h: (pkt.get_value_str(h) or "") for h in headers})
    return rows


def _to_float(v: str) -> float:
    try:
        return float(v) if v else 0.0
    except (TypeError, ValueError):
        return 0.0


def _to_int(v: str) -> int:
    try:
        return int(v) if v else 0
    except (TypeError, ValueError):
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return 0


def _empty(code: int, msg: str) -> Dict[str, Any]:
    return {"code": code, "msg": msg, "list": []}


def _parse_asset(pkt: MsgPacket) -> Dict[str, Any]:
    """解析资金查询结果 → {code, msg, list:[{cash, frozen_cash, market_value, total_asset}]}"""
    code, msg = _parse_code_msg(pkt)
    if code != 0:
        return _empty(code, msg)
    items = []
    for row in _iter_rows(pkt, 2):
        items.append({
            "cash": _to_float(row.get("cash", "")),
            "frozen_cash": _to_float(row.get("frozen_cash", "")),
            "market_value": _to_float(row.get("market_value", "")),
            "total_asset": _to_float(row.get("total_asset", "")),
        })
    return {"code": code, "msg": msg, "list": items}


def _parse_orders(pkt: MsgPacket) -> Dict[str, Any]:
    """解析委托查询结果 → {code, msg, list:[order_dict, ...]}"""
    code, msg = _parse_code_msg(pkt)
    if code != 0:
        return _empty(code, msg)
    items = []
    for row in _iter_rows(pkt, 2):
        volume = row.get("order_volume") or row.get("volume") or "0"
        status = row.get("order_status") or row.get("status") or ""
        items.append({
            "order_id": row.get("order_id", ""),
            "stock_code": row.get("stock_code", ""),
            # 柜台 order_type 数字串：股票 23=买入，24=卖出
            "order_type": _to_int(row.get("order_type", "")),
            "price_type": _to_int(row.get("price_type", "")),
            "price": _to_float(row.get("price", "")),
            "volume": _to_int(volume),
            "traded_volume": _to_int(row.get("traded_volume", "")),
            "traded_price": _to_float(row.get("traded_price", "")),
            "status": status,
            "order_time": row.get("order_time", ""),
            "order_remark": row.get("order_remark", ""),
            "status_msg": row.get("status_msg", ""),
        })
    return {"code": code, "msg": msg, "list": items}


def _parse_trades(pkt: MsgPacket) -> Dict[str, Any]:
    """解析成交查询结果 → {code, msg, list:[trade_dict, ...]}"""
    code, msg = _parse_code_msg(pkt)
    if code != 0:
        return _empty(code, msg)
    items = []
    for row in _iter_rows(pkt, 2):
        volume = row.get("volume") or row.get("traded_volume") or "0"
        price = row.get("price") or row.get("traded_price") or "0"
        # 柜台报文字段名是 traded_id / traded_time；保留 trade_id / trade_time 作兼容
        items.append({
            "trade_id": row.get("traded_id", ""),
            "order_id": row.get("order_id", ""),
            "stock_code": row.get("stock_code", ""),
            # 柜台 order_type 数字串：股票 23=买入，24=卖出
            "order_type": row.get("order_type", ""),
            "volume": _to_int(volume),
            "price": _to_float(price),
            "trade_time": row.get("traded_time", ""),
        })
    return {"code": code, "msg": msg, "list": items}


def _parse_positions(pkt: MsgPacket) -> Dict[str, Any]:
    """解析持仓查询结果 → {code, msg, list:[pos_dict, ...]}"""
    code, msg = _parse_code_msg(pkt)
    if code != 0:
        return _empty(code, msg)
    items = []
    for row in _iter_rows(pkt, 2):
        volume = row.get("volume", "0")
        available = row.get("avl_amt") or row.get("available") or "0"
        cost = row.get("avg_price") or row.get("cost") or "0"
        market_value = row.get("market_value", "0")
        items.append({
            "stock_code": row.get("stock_code", ""),
            "stock_name": row.get("stock_name") or row.get("name") or "",
            "volume": _to_int(volume),
            "available": _to_int(available),
            "cost": _to_float(cost),
            "market_value": _to_float(market_value),
        })
    return {"code": code, "msg": msg, "list": items}


def _parse_order_ack(pkt: MsgPacket) -> Dict[str, Any]:
    """解析下单应答 → {code, msg, list:[ack_dict, ...]}

    第二结果集字段未严格约定（可能包含 order_id / order_sysid 等），
    这里原样透传 dict，由前端展示层处理。
    """
    code, msg = _parse_code_msg(pkt)
    if code != 0:
        return _empty(code, msg)
    return {"code": code, "msg": msg, "list": _iter_rows(pkt, 2)}


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
    """查询资金 qry_ast → {code, msg, list:[asset_dict]}"""
    client = await get_rpc_client()
    pkt = await client.call("qry_ast")
    return _parse_asset(pkt)


async def qry_orders() -> Dict[str, Any]:
    """查询委托 qry_ord → {code, msg, list:[order_dict, ...]}"""
    client = await get_rpc_client()
    pkt = await client.call("qry_ord")
    return _parse_orders(pkt)


async def qry_trades() -> Dict[str, Any]:
    """查询成交 qry_mch → {code, msg, list:[trade_dict, ...]}"""
    client = await get_rpc_client()
    pkt = await client.call("qry_mch")
    return _parse_trades(pkt)


async def qry_positions() -> Dict[str, Any]:
    """查询持仓 qry_pos → {code, msg, list:[pos_dict, ...]}"""
    client = await get_rpc_client()
    pkt = await client.call("qry_pos")
    return _parse_positions(pkt)


async def ord_stk(
    stock_code: str,
    volume: int,
    price_type: int,
    price: float,
    order_type: str,
    remark: Optional[str] = None,
) -> Dict[str, Any]:
    """下单 ord_stk（等待柜台应答）

    协议同 qry_*：第 1 结果集 code/msg；第 2 结果集为下单回报（如 order_id）。
    成交细节仍通过 EvTrade.Test.Push 队列异步推送（ord_cfm / trd_cfm）。

    参数：
      order_type  柜台买卖类型数字串，股票场景：23=买入，24=卖出
      price_type  柜台价格类型数字：
                    5=最新价 11=指定价(限价) 14=对手价 44=市价 ...
      remark      委托备注，柜台透传；不传时取 settings.ORDER_REMARK（默认 "EvTrade.Test"）
    """
    client = await get_rpc_client()
    if remark is None:
        remark = settings.ORDER_REMARK
    pkt = await client.call(
        "ord_stk",
        headers="stock_code,volume,price_type,price,order_type,remark",
        values={
            "stock_code": stock_code,
            "volume": str(volume),
            "price_type": str(price_type),
            "price": str(price),
            "order_type": order_type,
            "remark": remark,
        },
    )
    return _parse_order_ack(pkt)


async def cancel_order(order_id: str) -> Dict[str, Any]:
    """撤单 cancel_ord（占位实现，未把 order_id 写入请求体）"""
    client = await get_rpc_client()
    pkt = await client.call("cancel_ord")
    return _parse_order_ack(pkt)
