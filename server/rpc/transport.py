"""
transport.py — RPClient 传输骨架（simplify-rpc-transport-thin + layered-architecture v13）

职责（传输层本分）：
- RPClient 类：维护 RabbitMQ 长连接、消息发布、in-flight pending futures
- reply listener：按 msgid 匹配 pending future
- push listener：消息循环 + 解码 + 委托给 PushDispatcher
- 全局单例 _rpc_client + get_rpc_client / close_rpc_client 生命周期
- 传输层 utilities：_clean_id（msgid/func 字符串清洗）、_wire_dump（报文 dump）
- 协议常量 re-export：RABBITMQ_URL / EXCHANGE_NAME / QUEUE_REQ / QUEUE_REPLY / QUEUE_PUSH
- push 业务编排已迁到 server/services/push/dispatcher.py（REQ-RPC-012）
- push 行提取已迁到 server/rpc/parsers_push.py

v13 分层改造：
- RPClient 继承自 server.infra.mq.MessageQueueClient（基类封装 aio_pika RMQ 长连接）
- connect() 委托给 super().connect()（声明 exchange + req/reply/push 队列）
- publish() 委托给 super().publish()（publisher confirm + timeout）
- listen_replies/listen_pushs 委托给 super().listen_*(callback)（基类做 iterator + process）
- 业务级字段（pending / _publish_confirm_timeout / _dispatcher）+ 业务方法（_handle_reply / call / _log_reply / _count_reply_rows / close）保留
"""
import asyncio
import logging
from typing import Any, Dict, Optional


from msgpacket import MsgPacket, MSG_TYPE_REQUEST

from server.config import settings
from server.infra.mq import MessageQueueClient
from server.services.push.dispatcher import PushDispatcher

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


# ──────────────────────────── RPClient ────────────────────────────

class RPClient(MessageQueueClient):
    """业务级 RMQ 客户端（继承 MessageQueueClient 传输基类）。

    本类负责：
    - 业务级 pending future 管理
    - MsgPacket 构造 / 解码 / 报文 dump
    - publisher confirm 超时 → RuntimeError 转换
    - push 业务 dispatcher 编排（PushDispatcher）
    - 协议常量到队列名的绑定
    """

    def __init__(self, url: str = RABBITMQ_URL):
        super().__init__(url)
        # 业务级字段（inherited from MessageQueueClient: conn/channel/exchange/reply_queue/push_queue/url）
        self.pending: dict = {}  # msgid -> asyncio.Future
        # publisher confirm 超时（防 broker 不 ack 时永久挂起）；保留旧字段名兼容测试
        self._publish_confirm_timeout: float = 5.0
        # push 业务编排器（connect 时构造，simplify-rpc-transport-thin 后迁出）
        self._dispatcher: Optional[PushDispatcher] = None

    async def connect(self):
        # 幂等守卫：已连接且未关闭 → 直接返回（避免 FastAPI 重启/双启动时重复 declare）
        if self.conn is not None and not self.conn.is_closed:
            log.debug("RPClient.connect: already connected, skip")
            return
        # 委托基类声明 exchange + req/reply/push 队列 + bind
        await super().connect(
            exchange_name=EXCHANGE_NAME,
            reply_queue_name=QUEUE_REPLY,
            push_queue_name=QUEUE_PUSH,
            request_queue_name=QUEUE_REQ,
        )
        # 构造 push 业务编排器（在 listener 启动前完成，避免漏掉首批 push）
        self._dispatcher = PushDispatcher(self)
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

        基类 MessageQueueClient.listen_replies 负责 iterator + message.process；
        本方法只提供 on_message 回调：log wire 长度 + 委托给 _handle_reply。
        """
        async def _on_reply_wire(wire_data: bytes):
            log.info("RPClient <<< reply wire_len=%d", len(wire_data))
            await self._handle_reply(wire_data)
        await super().listen_replies(_on_reply_wire)

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
        """监听 EvTrade.Test.Push 队列，把柜台主动推送转交给 dispatcher。

        基类 MessageQueueClient.listen_pushs 负责 iterator + message.process；
        本方法提供 on_message 回调：decode + 委托给 dispatcher。

        柜台不会回包给 ord_stk 的请求方（fire-and-forget），
        真正的成交通知通过 push 队列异步推送：
          - ord_cfm : 委托状态/成交通知（首次报单、状态变化）
          - trd_cfm : 成交回报
        # change consolidate-position-data-flow: pos_cfm / ast_cfm 不再订阅
        # (xtquant broker 协议不发送这两个事件名)

        协议格式与 ANSWER 类似（func + headers + rows），但无 error_code 语义。
        """
        if not self._dispatcher:
            log.warning("RPClient push listener skipped: dispatcher not initialized")
            return
        async def _on_push_wire(wire: bytes):
            try:
                pkt = MsgPacket.decode(wire)
                func = _clean_id(pkt.func())
                mt = self._safe_msg_type(pkt)
                log.info(
                    "RPClient.push <<< wire_len=%d func=%r type=%r",
                    len(wire), func, mt,
                )
                await self._dispatcher.dispatch(pkt, func, mt, len(wire))
            except Exception as e:
                log.exception("RPClient.push decode/handle error: %s", e)
        await super().listen_pushs(_on_push_wire)

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
            # 委托基类 publish（封装 Message 构造 + publisher confirm + wait_for timeout）
            await super().publish(
                wire_data, routing_key=QUEUE_REQ, timeout=self._publish_confirm_timeout,
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
        # 保留原行为：仅关闭连接，不清空 conn/channel 字段（让基类幂等守卫正常工作）
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
