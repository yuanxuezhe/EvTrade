"""
transport.py — RPClient 传输层（connect / call / listen replies / listen pushs）

职责：
- RPClient 类：维护 RabbitMQ 长连接、消息发布、in-flight pending futures
- 全局单例 _rpc_client + get_rpc_client / close_rpc_client 生命周期
- 传输层 utilities：_clean_id（msgid/func 字符串清洗）、_wire_dump（报文 dump）
- push 处理 helpers：_iter_push_rows（行提取）、_run_handle_push（落库）、
  _resolve_active_trd_date_safe（注入 trd_date）、_dispatch_push（单条 push 编排）、
  _log_push_interaction（push 交互日志）
- 常量：MAX_PENDING（防积压）、_PUSH_CHANNEL（推送类型 → WS channel）
- 协议常量 re-export：RABBITMQ_URL / EXCHANGE_NAME / QUEUE_REQ / QUEUE_REPLY / QUEUE_PUSH
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional

import aio_pika
from aio_pika import ExchangeType, Message

from msgpacket import MsgPacket, MSG_TYPE_REQUEST, MSG_TYPE_PUSH

from server.config import settings
from server.ws.manager import ws_manager

# 注: 避免循环导入, format_ts / logflow 在函数内 lazy import
#   transport -> utils.time -> utils.__init__ -> logflow (ok, no cycle)
#   但 services.__init__ -> reconcile -> rpc.client -> rpc.transport 仍可能循环
#   所以此处不顶层 from server.utils.time import format_ts
#   log_interaction / 方向常量同理, 在函数内 lazy import

log = logging.getLogger(__name__)


# ──────────────────────────── 协议常量 ────────────────────────────

# 兼容旧引用：保留模块级常量名（值来自 config）
RABBITMQ_URL = settings.RABBITMQ_URL
EXCHANGE_NAME = settings.EXCHANGE_NAME
QUEUE_REQ = settings.QUEUE_REQ
QUEUE_REPLY = settings.QUEUE_REPLY
QUEUE_PUSH = settings.QUEUE_PUSH

# 在途 RPC 调用的最大并发数（防止柜台慢应答时无限累积）
MAX_PENDING = 100

# 推送类型 → WS channel
_PUSH_CHANNEL = {
    "ord_cfm": "order_update",
    "trd_cfm": "trade_update",
    "pos_cfm": "position_update",
    "ast_cfm": "asset_update",
}


# ──────────────────────── 传输层工具函数 ────────────────────────

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


# ──────────────────────── push 处理 helpers ────────────────────────

def _iter_push_rows(pkt: MsgPacket) -> List[Dict[str, Any]]:
    """把 push 包里所有结果集的所有行原样取出，header 名 → 字符串值。

    与 parsers_common._iter_rows 思路不同：push 的字段名没有统一约定
    （ord_cfm / trd_cfm 各异），这里不强行类型转换，直接交由前端展示层处理。
    """
    rows: List[Dict[str, Any]] = []
    headers_str = pkt.get_headers() or ""
    headers = [h.strip() for h in headers_str.split(",") if h.strip()]

    for rs in range(1, pkt.result_set_count() + 1):
        if rs > 1:
            if not pkt.next_result_set():
                break
        pkt.reset_cursor()
        while pkt.fetch_next():
            row = {h: (pkt.get_value_str(h) or "") for h in headers}
            rows.append(row)
    return rows


def _run_handle_push(func: str, row: Dict[str, Any], ts: str) -> Optional[Dict[str, Any]]:
    """push 落库 helper（REQ-PUSH-006）：新线程内跑 SessionLocal + handle_push + commit。

    设计要点：
    - 在新线程中执行（loop.run_in_executor 包裹），不阻塞 push listener 的 event loop
    - SessionLocal 每次新建，独立 session 安全无共享状态
    - 异常向上抛回 await 处，由 listener 捕获并 log
    - handle_push 同步签名不变（向后兼容 test_push_handlers.py 11 用例）
    - 返回 handler 的重组包结果（OrderOut/TradeOut 兼容 dict）
    """
    from server.db import SessionLocal
    from server.services.push_handlers import handle_push
    db = SessionLocal()
    try:
        result = handle_push(db, func, row, ts)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _resolve_active_trd_date_safe() -> Optional[str]:
    """短连接查当前激活交易日（v8 增：push 链路注入 trd_date 用）

    Returns:
        8 位 YYYYMMDD,或 None（未做日初 / DB 异常时）

    设计要点：
    - 每次调用都新开 SessionLocal（无状态依赖，安全）
    - 异常返回 None 而非 raise（不阻塞 push listener 主循环）
    - 不传 row 参数给 ws：返回 None 时不注入 trd_date,前端用 _today_yyyymmdd 兜底
    """
    try:
        from server.db import SessionLocal
        from server.services.guards import resolve_active_trd_date
        db = SessionLocal()
        try:
            return resolve_active_trd_date(db)
        finally:
            db.close()
    except Exception as e:
        # 短连接异常（DB 锁 / disconnect）不应中断 push 链路
        log.warning("_resolve_active_trd_date_safe failed: %s", e)
        return None


def _log_push_interaction(func: str, wire_len: int, msg_type: str, msg_id: str):
    """记 [svc<-rpc] push 交互日志 (server-interaction-logging REQ-LOG-003)。

    push 是 fire-and-forget，msg_id 来自 broker 推送（可能为空），
    没有现成 trace_id 时用 UUID 生成新的。
    """
    import uuid as _uuid
    from server.utils.logflow import DIR_SVC_FROM_RPC, log_interaction

    push_trace = (msg_id or "").strip().strip("\x00").strip()[:8] or _uuid.uuid4().hex[:8]
    log_interaction(
        DIR_SVC_FROM_RPC,
        "push func={} wire_len={}".format(func, wire_len),
        data={"func": func, "wire_len": wire_len, "msg_type": msg_type},
        level="info",
        trace_id=push_trace,
    )
    return push_trace


def _log_push_broadcast(channel: str, data: Any, ts: str, func: str, active_trd_date: Optional[str], push_trace: str):
    """记广播日志并调用 ws_manager.broadcast。"""
    from server.utils.logflow import DIR_SVC_TO_FRONT, log_interaction

    payload = {
        "type": func,
        "channel": channel,
        "ts": ts,
        "data": data,
    }
    log.info(
        "RPClient.push broadcast → %s (trd_date=%s)%s",
        channel,
        active_trd_date or "?",
        ("\n" + "\n".join(
            "  " + k + " = " + repr(v)
            for k, v in sorted(data.items())
        )) if data else " (empty row)",
    )
    log_interaction(
        DIR_SVC_TO_FRONT,
        "ws broadcast channel={} (push)".format(channel),
        data={"channel": channel, "payload": payload},
        level="info",
        trace_id=push_trace,
    )
    return payload


# ──────────────────────────── RPClient ────────────────────────────

class RPClient:
    def __init__(self, url: str = RABBITMQ_URL):
        self.url = url
        self.conn: Optional[aio_pika.Connection] = None
        self.channel: Optional[aio_pika.Channel] = None
        self.exchange: Optional[aio_pika.Exchange] = None
        self.reply_queue: Optional[aio_pika.Queue] = None
        self.push_queue: Optional[aio_pika.Queue] = None
        self.pending: dict = {}  # msgid -> asyncio.Future
        # publisher confirm 超时（防 broker 不 ack 时永久挂起）
        self._publish_confirm_timeout: float = 5.0

    async def connect(self):
        # 幂等守卫：已连接且未关闭 → 直接返回（避免 FastAPI 重启/双启动时重复 declare）
        if self.conn is not None and not self.conn.is_closed:
            log.debug("RPClient.connect: already connected, skip")
            return
        self.conn = await aio_pika.connect_robust(self.url)
        # publisher_confirms=True 让 publish() 等 broker ack，broker 重启/磁盘满不再静默丢包
        self.channel = await self.conn.channel(publisher_confirms=True)
        self.exchange = await self.channel.declare_exchange(
            EXCHANGE_NAME, ExchangeType.TOPIC, durable=True,
        )
        # 显式 declare + bind 三条 durable 队列（REQ-RPC-007）
        # routing_key 用队列名本身（topic exchange 支持字面 key，不依赖柜台预绑定）
        req_q = await self.channel.declare_queue(QUEUE_REQ, durable=True)
        await req_q.bind(self.exchange, routing_key=QUEUE_REQ)
        self.reply_queue = await self.channel.declare_queue(QUEUE_REPLY, durable=True)
        await self.reply_queue.bind(self.exchange, routing_key=QUEUE_REPLY)
        self.push_queue = await self.channel.declare_queue(QUEUE_PUSH, durable=True)
        await self.push_queue.bind(self.exchange, routing_key=QUEUE_PUSH)
        asyncio.ensure_future(self._listen_replies())
        asyncio.ensure_future(self._listen_pushs())
        log.info(
            "RPClient connected, listening on reply=%s push=%s (exchange=%s, confirms=on)",
            QUEUE_REPLY, QUEUE_PUSH, EXCHANGE_NAME,
        )

    # ── reply listener ─────────────────────────────────────

    async def _listen_replies(self):
        """监听回复队列，通过 msgid 匹配 pending 的 future。

        协议要求柜台在应答包中回写请求的 msgid；若柜台未回写，
        这里的 "msg_id not in pending" 日志会指明收到的 msgid 是什么、
        以及当前等待的 msgid 列表，便于排查链路问题。
        """
        log.info("RPClient reply listener started")
        async with self.reply_queue.iterator() as qiter:
            async for msg in qiter:
                async with msg.process():
                    wire_data = msg.body
                    log.info("RPClient <<< reply wire_len=%d", len(wire_data))
                    await self._handle_reply(wire_data)

    async def _handle_reply(self, wire_data: bytes):
        """解析 reply 报文并匹配 pending future。"""
        try:
            pkt = MsgPacket.decode(wire_data)
            msg_id = _clean_id(pkt.msg_id())
            func = _clean_id(pkt.func())
            mt = self._safe_msg_type(pkt)
            log.info(
                "RPClient decoded func=%r type=%r msg_id=%r pending=%d",
                func, mt, msg_id, len(self.pending),
            )
            reply_dump = _wire_dump(pkt)
            if reply_dump:
                log.debug("RPClient <<< wire:\n%s", reply_dump)
            if msg_id and msg_id in self.pending:
                future = self.pending.pop(msg_id)
                if not future.done():
                    future.set_result(pkt)
                log.info(
                    "RPClient resolved msg_id=%s, remaining_pending=%d",
                    msg_id, len(self.pending),
                )
            else:
                log.warning(
                    "RPClient msg_id=%r not in pending (have %d, keys=%s)",
                    msg_id, len(self.pending), list(self.pending.keys()),
                )
        except Exception as e:
            log.exception("RPClient decode/handle error: %s", e)

    # ── push listener ──────────────────────────────────────

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
            log.warning("RPClient push listener skipped: push_queue not declared")
            return
        log.info("RPClient push listener started, queue=%s", QUEUE_PUSH)
        async with self.push_queue.iterator() as qiter:
            async for msg in qiter:
                async with msg.process():
                    wire = msg.body
                    try:
                        pkt = MsgPacket.decode(wire)
                        func = _clean_id(pkt.func())
                        mt = self._safe_msg_type(pkt)
                        log.info(
                            "RPClient.push <<< wire_len=%d func=%r type=%r",
                            len(wire), func, mt,
                        )
                        await self._dispatch_push(pkt, func, mt, len(wire))
                    except Exception as e:
                        log.exception("RPClient.push decode/handle error: %s", e)

    async def _dispatch_push(self, pkt: MsgPacket, func: str, msg_type: str, wire_len: int):
        """处理单条 push 消息：交互日志 → 路由 → 落库 → WS 广播。

        从 _listen_pushs 中拆分出来，使监听循环保持简洁，
        并将 push 处理的具体逻辑集中在一个可测试的方法中。
        """
        push_trace = _log_push_interaction(func, wire_len, msg_type, pkt.msg_id())

        channel = _PUSH_CHANNEL.get(func)
        if not channel:
            log.warning("RPClient.push ignore unknown func=%r", func)
            return

        # v8 增: 推送 payload 注入 trd_date(权威源 = 当前激活交易日)
        active_trd_date = _resolve_active_trd_date_safe()

        from server.utils.time import format_ts
        push_ts = format_ts(tz='local')

        for row in _iter_push_rows(pkt):
            enriched_row = {**row, "trd_date": active_trd_date} if active_trd_date else row

            # v8 持久化（异步）：run_in_executor 包裹，不阻塞 event loop（REQ-PUSH-006）
            handler_result = await self._run_push_handler(func, enriched_row, push_ts)

            if func == "trd_cfm":
                await self._broadcast_trade_cfm(
                    handler_result, channel, push_ts, func, active_trd_date, push_trace,
                )
            else:
                self._broadcast_generic(
                    handler_result, enriched_row, channel, push_ts, func, active_trd_date, push_trace,
                )

    async def _run_push_handler(self, func: str, row: Dict[str, Any], ts: str) -> Optional[Dict[str, Any]]:
        """在线程池中执行 push 落库，异常捕获不中断广播链路。"""
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None, _run_handle_push, func, row, ts,
            )
        except Exception as e:
            log.error("RPClient.push handle_push error: %s", e)
            return None

    def _broadcast_trade_cfm(
        self,
        handler_result: Optional[Dict[str, Any]],
        channel: str,
        ts: str,
        func: str,
        active_trd_date: Optional[str],
        push_trace: str,
    ):
        """trd_cfm：广播成交 + 同步委托状态。

        NOTE: 内部调用 ws_manager.broadcast 返回 coroutine，
        用 asyncio.ensure_future 调度，不阻塞后续行的处理。
        """
        if not isinstance(handler_result, dict) or not handler_result.get("trade"):
            return

        trade_data = handler_result["trade"]
        order_data = handler_result.get("order")

        trade_payload = _log_push_broadcast(
            channel, trade_data, ts, func, active_trd_date, push_trace,
        )
        asyncio.ensure_future(ws_manager.broadcast(channel, trade_payload, trace_id=push_trace))

        if order_data:
            order_payload = _log_push_broadcast(
                "order_update", order_data, ts, "ord_cfm", active_trd_date, push_trace,
            )
            asyncio.ensure_future(ws_manager.broadcast("order_update", order_payload, trace_id=push_trace))

    def _broadcast_generic(
        self,
        handler_result: Optional[Dict[str, Any]],
        enriched_row: Dict[str, Any],
        channel: str,
        ts: str,
        func: str,
        active_trd_date: Optional[str],
        push_trace: str,
    ):
        """ord_cfm / pos_cfm / ast_cfm：用 handler 结果或 fallback 行数据广播。

        NOTE: 内部调用 ws_manager.broadcast 返回 coroutine，
        用 asyncio.ensure_future 调度，不阻塞后续行的处理。
        """
        broadcast_data = handler_result if handler_result is not None else enriched_row
        payload = _log_push_broadcast(
            channel, broadcast_data, ts, func, active_trd_date, push_trace,
        )
        asyncio.ensure_future(ws_manager.broadcast(channel, payload, trace_id=push_trace))

    # ── shared helpers ─────────────────────────────────────

    def _safe_msg_type(self, pkt: MsgPacket) -> str:
        """安全读取 msg_type 为可打印字符，失败返回 '?'。"""
        try:
            return chr(pkt.msg_type())
        except Exception:
            return "?"

    # ── RPC call ───────────────────────────────────────────

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

        # 在途 RPC 数量保护（柜台慢应答时避免 pending 无限累积）
        if len(self.pending) >= MAX_PENDING:
            raise RuntimeError(
                f"RPC pending 队列已满 (>{MAX_PENDING})，请等待柜台应答"
            )

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
        log.info(
            "RPClient.call >>> func=%s msg_id=%s pending=%d wire_len=%d",
            func, msg_id, len(self.pending), len(wire_data),
        )
        req_dump = _wire_dump(pkt)
        if req_dump:
            log.debug("RPClient.call >>> wire:\n%s", req_dump)

        # publisher confirm（REQ-RPC-008）：等 broker ack，超时则清 pending + 抛错
        # v10 增: 记 [svc->rpc] 调用日志 (server-interaction-logging REQ-LOG-003)
        from server.utils.logflow import DIR_SVC_TO_RPC, log_interaction
        log_interaction(
            DIR_SVC_TO_RPC,
            "call func={}".format(func),
            data={"values": values or {}, "msg_id": msg_id},
            level="info",
            trace_id=msg_id,
        )
        try:
            await asyncio.wait_for(
                self.exchange.publish(
                    Message(body=wire_data), routing_key=QUEUE_REQ
                ),
                timeout=self._publish_confirm_timeout,
            )
        except asyncio.TimeoutError:
            self.pending.pop(msg_id, None)
            log.error(
                "RPClient.call publish TIMEOUT func=%s msg_id=%s after %.1fs (broker no-ack?)",
                func, msg_id, self._publish_confirm_timeout,
            )
            log_interaction(
                DIR_SVC_TO_RPC,
                "publish TIMEOUT func={}".format(func),
                data={"timeout_s": self._publish_confirm_timeout, "msg_id": msg_id},
                elapsed_ms=self._publish_confirm_timeout * 1000,
                level="error",
                trace_id=msg_id,
            )
            raise RuntimeError(
                f"RPC publish unconfirmed after {self._publish_confirm_timeout}s "
                f"(broker not ack, check broker status / disk)"
            )

        try:
            reply_pkt = await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            # 超时清理 pending，避免内存泄漏 + 防止后续应答误匹配
            self.pending.pop(msg_id, None)
            log.warning(
                "RPClient.call TIMEOUT func=%s msg_id=%s after %.1fs",
                func, msg_id, timeout,
            )
            from server.utils.logflow import DIR_SVC_FROM_RPC, log_interaction
            log_interaction(
                DIR_SVC_FROM_RPC,
                "TIMEOUT func={}".format(func),
                data={"timeout_s": timeout, "msg_id": msg_id},
                elapsed_ms=timeout * 1000,
                level="warning",
                trace_id=msg_id,
            )
            raise

        # v10 增: 记 [svc<-rpc] reply 日志 (含 code / rows)
        self._log_reply(func, reply_pkt, msg_id)

        return reply_pkt

    def _log_reply(self, func: str, reply_pkt: MsgPacket, msg_id: str):
        """记录 RPC reply 的交互日志（code / row_count），异常不向上抛。"""
        try:
            from server.rpc.parsers_common import _parse_code_msg
            from server.utils.logflow import DIR_SVC_FROM_RPC, log_interaction

            code, _msg = _parse_code_msg(reply_pkt)
            row_count = self._count_reply_rows(reply_pkt)
            log_interaction(
                DIR_SVC_FROM_RPC,
                "reply func={} code={} rows={}".format(func, code, row_count),
                data={"code": code, "row_count": row_count, "msg_id": msg_id},
                level="info",
                trace_id=msg_id,
            )
        except Exception:
            pass  # 日志失败不影响业务

    def _count_reply_rows(self, reply_pkt: MsgPacket) -> int:
        """估算 reply 第二结果集的 row 数（不强制解析，避免开销）。"""
        try:
            if reply_pkt.result_set_count() >= 2:
                reply_pkt.select_result_set(2)
                reply_pkt.reset_cursor()
                count = 0
                while reply_pkt.fetch_next():
                    count += 1
                return count
        except Exception:
            pass
        return 0

    async def close(self):
        if self.conn:
            await self.conn.close()


# ──────────────────────────── 全局单例 ────────────────────────────

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
