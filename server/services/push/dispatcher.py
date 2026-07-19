"""
push/dispatcher.py — push 业务编排器（编排层，不持有 IO 实现）

RPClient 在 connect() 时构造 `PushDispatcher(self)`；
push listener 收到消息后调 `await dispatcher.dispatch(pkt, func, msg_type, wire_len)`。

编排流程：
  1. 交互日志（log_helpers._log_push_interaction）
  2. 路由查表（routes._PUSH_CHANNEL）
  3. 激活交易日注入（run_handlers._resolve_active_trd_date_safe）
  4. push 行迭代（parsers_push._iter_push_rows）
  5. 落库（run_handlers._run_handle_push 在线程池）
  6. 广播（按 func 类型分派 _broadcast_trade_cfm / _broadcast_generic）

依赖收敛：本文件只 import 本子包（routes / run_handlers / log_helpers），
跨层引用（rpc.parsers_push / ws.manager / db / utils.time）全部延迟到调用点。
"""
import asyncio
import logging
from typing import Any, Dict, Optional

from msgpacket import MsgPacket

from server.services.push.routes import _PUSH_CHANNEL
from server.services.push.run_handlers import (
    _resolve_active_trd_date_safe,
    _run_handle_push,
)
from server.services.push.log_helpers import (
    _log_push_broadcast,
    _log_push_interaction,
)

log = logging.getLogger(__name__)


class PushDispatcher:
    """push 业务编排器（按职责拆出 routes / run_handlers / log_helpers 三个 helper）。"""

    def __init__(self, rpc_client) -> None:
        # 仅持引用，不做副作用；rpc_client 主要用于 dispatcher 拿到 push_queue
        # 等上下文（当前实现未直接用，预留扩展位）
        self._rpc_client = rpc_client

    async def dispatch(self, pkt: MsgPacket, func: str, msg_type: str, wire_len: int) -> None:
        """处理单条 push 消息：交互日志 → 路由 → 落库 → WS 广播。"""
        push_trace = _log_push_interaction(func, wire_len, msg_type, pkt.msg_id())

        channel = _PUSH_CHANNEL.get(func)
        if not channel:
            log.warning("RPClient.push ignore unknown func=%r", func)
            return

        # 推送 payload 注入 trd_date（权威源 = 当前激活交易日）
        active_trd_date = _resolve_active_trd_date_safe()

        from server.utils.time import format_ts
        push_ts = format_ts(tz='local')

        # lazy import: parsers_push 在 rpc 层，services 层反向依赖 rpc 不优雅
        # 但 _iter_push_rows 是纯 msgpacket 解析，无业务依赖，安全
        from server.rpc.parsers_push import _iter_push_rows
        for row in _iter_push_rows(pkt):
            enriched_row = {**row, "trd_date": active_trd_date} if active_trd_date else row

            # 持久化（异步）：run_in_executor 包裹，不阻塞 event loop
            handler_result = await self._run_push_handler(func, enriched_row, push_ts)

            if func == "trd_cfm":
                self._broadcast_trade_cfm(
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
    ) -> None:
        """trd_cfm：广播成交 + 同步委托状态。

        内部调用 ws_manager.broadcast 返回 coroutine，
        用 asyncio.ensure_future 调度，不阻塞后续行的处理。
        """
        if not isinstance(handler_result, dict) or not handler_result.get("trade"):
            return

        from server.ws.manager import ws_manager

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
    ) -> None:
        """ord_cfm / trd_cfm：用 handler 结果或 fallback 行数据广播。

        v78 (REQ-TRADE-029): handler_result is None → 直接跳过 ws 广播.
        这是 "已报后续不处理" 的另一半 — handler 已决定不再处理, dispatcher 不 fallback
        enriched_row (否则会发空变更, 前端无意义重复刷新).

        内部调用 ws_manager.broadcast 返回 coroutine，
        用 asyncio.ensure_future 调度，不阻塞后续行的处理。
        """
        from server.ws.manager import ws_manager

        # v78: handler 显式 None → 跳过广播 (避免 ws 噪声)
        if handler_result is None:
            return

        broadcast_data = handler_result
        payload = _log_push_broadcast(
            channel, broadcast_data, ts, func, active_trd_date, push_trace,
        )
        asyncio.ensure_future(ws_manager.broadcast(channel, payload, trace_id=push_trace))


__all__ = ["PushDispatcher"]