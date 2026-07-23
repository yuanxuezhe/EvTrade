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

def _do_junk_update_sync(order_no: str, trd_date: str, status_msg: str) -> Optional["Order"]:
    """v84: 同步执行废单 DB 写入 (run_in_executor 调用, 不阻塞 event loop).

    返回更新后的 order 对象, 由主协程负责 ws push (主协程才有 event loop).
    异常向外抛, 由 _handle_ord_stk_reply_junk 顶层 try/except 兜底.
    """
    # 延迟 import: tables 层依赖 MySQL 连接, 启动时不应触发
    from server.tables import Orders
    order = Orders.query_one(trd_date=trd_date, order_no=order_no)
    if not order:
        log.warning("v84 junk update: trd_date=%s order_no=%s not found in Orders", trd_date, order_no)
        return None
    order.status = "57"  # broker JUNK 废单
    order.status_msg = status_msg[:240] if status_msg else "broker reject"
    if not order.cancelled_volume:
        order.cancelled_volume = order.volume or 0
    order.update(Orders, trd_date=trd_date, order_no=order_no)
    log.info(
        "v84 junk order updated: trd_date=%s order_no=%s status=57 msg=%r",
        trd_date, order_no, status_msg,
    )
    return order


# v84: msgid → (order_no, trd_date, stock_code, created_at_ts)
# ord_stk 下单时写入, transport._handle_reply 收到 code!=0 应答时按 msgid 查找更新 Order.
# TTL 60s 自动清理 (避免内存泄漏). 这是 fire-and-forget 防护机制:
# 即使 place.py 同步 await 路径被中断/超时, 后续 broker 异步应答也能找到原 order_no 更新为废单.
_MSGID_ORDERNO_CACHE: Dict[str, tuple] = {}
_MSGID_ORDERNO_TTL_SEC = 60.0


def _register_msgid_orderno(msg_id: str, order_no: str, trd_date: str, stock_code: str) -> None:
    """v84: 下单时注册 msgid → (order_no, trd_date, stock_code) 映射."""
    if not msg_id or not order_no:
        return
    import time as _time
    _MSGID_ORDERNO_CACHE[msg_id] = (order_no, trd_date, stock_code, _time.time())


def _lookup_msgid_orderno(msg_id: str) -> Optional[tuple]:
    """v84: 应答时按 msgid 查 (order_no, trd_date, stock_code, ts). 命中后调用方负责清缓存."""
    if not msg_id:
        return None
    entry = _MSGID_ORDERNO_CACHE.get(msg_id)
    if not entry:
        return None
    import time as _time
    order_no, trd_date, stock_code, ts = entry
    if _time.time() - ts > _MSGID_ORDERNO_TTL_SEC:
        _MSGID_ORDERNO_CACHE.pop(msg_id, None)
        return None
    return entry


def _evict_msgid_orderno(msg_id: str) -> None:
    """v84: 显式清除 (成功应答后避免 cache 残留)."""
    _MSGID_ORDERNO_CACHE.pop(msg_id, None)


async def _msgid_cache_gc_loop(interval_sec: float = 30.0) -> None:
    """v84: 定期清理过期 cache (daemon task, 永不抛错)."""
    import time as _time
    while True:
        try:
            await asyncio.sleep(interval_sec)
            now = _time.time()
            expired = [k for k, v in _MSGID_ORDERNO_CACHE.items() if now - v[3] > _MSGID_ORDERNO_TTL_SEC]
            for k in expired:
                _MSGID_ORDERNO_CACHE.pop(k, None)
            if expired:
                log.debug("v84 msgid cache GC: evicted %d expired entries (remaining=%d)", len(expired), len(_MSGID_ORDERNO_CACHE))
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.warning("v84 msgid cache GC loop error: %s", e)


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
        # v84: 启动 msgid cache GC daemon
        asyncio.ensure_future(_msgid_cache_gc_loop())
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

            # v84: ord_stk 应答且 code!=0 → 按 msgid 匹配 order_no 异步废单
            # 设计: 错误码 != 0 → 缓存中按 msgid 找到原 order_no + trd_date, 更新委托为废单 + 错误信息
            #       错误码 == 0 → 不处理 (broker ord_cfm push 会异步更新真实状态)
            # 时序: place.py _submit_rpc_async 同步等 ack 已被改写跳过 code!=0 写, 所以不会双重更新
            if func == "ord_stk" and msg_id:
                await self._handle_ord_stk_reply_junk(pkt, msg_id)
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
        msgid_meta: Optional[Dict[str, str]] = None,
    ) -> MsgPacket:
        """发送 RPC 请求并等待应答。

        msgid 由 MsgPacket 构造时自动生成（UUID v4 hex，32 字符）。
        协议要求柜台在应答包中回写该 msgid，否则本调用会等到 timeout。

        可选参数：
          headers: 逗号分隔的字段名（如 "stock_code,volume,price"），用于带请求体的调用。
          values:  字段名 → 字符串值的 dict；会在 headers 设置后写入第一行。
          msgid_meta (v84): dict 含 order_no / trd_date / stock_code。
            msgid 生成后会自动注册到 _MSGID_ORDERNO_CACHE,
            后续 transport._handle_reply 收到 func=ord_stk 且 code!=0 应答时按 msgid 反查,
            找到原 order_no 异步更新为废单 + msg。code==0 时 cache 不清 (等 TTL GC)。
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

        # v84: msgid_meta 预注册 → _MSGID_ORDERNO_CACHE (供 transport _handle_reply 反查)
        if msgid_meta:
            _register_msgid_orderno(
                msg_id,
                msgid_meta.get("order_no", ""),
                msgid_meta.get("trd_date", ""),
                msgid_meta.get("stock_code", ""),
            )
            log.debug(
                "v84 msgid registered: msgid=%s order_no=%s trd_date=%s stock_code=%s",
                msg_id,
                msgid_meta.get("order_no", ""),
                msgid_meta.get("trd_date", ""),
                msgid_meta.get("stock_code", ""),
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
            _evict_msgid_orderno(msg_id)  # v84: publish 超时清 cache
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
            _evict_msgid_orderno(msg_id)  # v84: wait_for 超时清 cache
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

    async def _handle_ord_stk_reply_junk(self, reply_pkt: "MsgPacket", msg_id: str) -> None:
        """v84: 处理 ord_stk 应答的废单路径 (code != 0).

        流程:
          1. 解 ack.code / ack.msg
          2. code == 0 → 跳过 (broker ord_cfm push 会异步推真实状态)
          3. code != 0 → 按 msgid 在 cache 中查 (order_no, trd_date, stock_code)
             → 用 Tables API 更新 Order 为 status=57 + status_msg + cancelled_volume=volume
             → ws_manager.broadcast('order_update') 通知前端
             → 清 cache (避免长期占用)

        异常隔离: 整个函数 try/except 包裹, 不影响 reply listener 继续跑.
        线程模型: 此函数在 reply listener 协程中执行; DB 写入 run_in_executor 不阻塞 event loop.
        """
        try:
            from server.rpc.parsers_common import _parse_code_msg
            code, ack_msg = _parse_code_msg(reply_pkt)
            try:
                code_int = int(code) if code not in (None, "", b"") else -1
            except (TypeError, ValueError):
                code_int = -1

            if code_int == 0:
                log.debug("v84 ord_stk reply code=0 skip (broker ord_cfm will async update)")
                return

            entry = _lookup_msgid_orderno(msg_id)
            if not entry:
                log.warning(
                    "v84 ord_stk reply code=%s but msgid=%s NOT in cache (expired or never registered)",
                    code_int, msg_id,
                )
                return
            order_no, trd_date, stock_code, _ts = entry

            log.warning(
                "v84 ord_stk JUNK detected: msgid=%s code=%s msg=%r order_no=%s trd_date=%s stock_code=%s",
                msg_id, code_int, ack_msg, order_no, trd_date, stock_code,
            )

            # 异步线程池执行 DB 写入 (避免阻塞 reply listener event loop)
            loop = asyncio.get_event_loop()
            updated_order = await loop.run_in_executor(
                None, _do_junk_update_sync, order_no, trd_date, ack_msg or f"broker reject code={code_int}",
            )
            # ws push 必须在主 event loop (run_in_executor 线程没有 loop)
            if updated_order is not None:
                try:
                    from server.services.push.helpers import _order_to_out_dict
                    from server.ws.manager import ws_manager
                    await ws_manager.broadcast("order_update", _order_to_out_dict(updated_order))
                except Exception as push_err:
                    log.warning("v84 junk update ws push failed: %s", push_err)

            # 显式清 cache (无论 DB 更新成功与否, 避免长期占用)
            _evict_msgid_orderno(msg_id)
        except Exception as e:
            log.exception("v84 _handle_ord_stk_reply_junk error: %s", e)

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
