"""order_broadcast.py — 统一的委托 ws 推送 helper

跨 api/orders + rpc/transport 共享的推送 helper, 包装成与 push/dispatcher.py
同款 ws payload (前端 ws_dispatch.js t='ord_cfm' 才识别):

    { type: 'ord_cfm', channel: 'order_update', ts, data: <order fields> }

注意: 不能直接 broadcast('order_update', _order_to_out_dict(...)) 推裸 dict —
前端 ws_dispatch t='order_update' 不识别, 会默默丢失.
统一走 _broadcast_order_cfm helper.
"""
import asyncio
import logging
from datetime import datetime
from typing import Any, Optional

log = logging.getLogger(__name__)


def _broadcast_order_cfm(order: Any, trace_id: Optional[str] = None) -> None:
    """统一的委托状态 ws 推送 (供 place.py / cancel.py / transport.py 调用).

    Args:
        order: server.tables.orders.Row 实例 (有 _to_out_dict 字段)
        trace_id: 可选追踪 ID (放 log + ws payload), 一般是 order_no
    """
    try:
        from server.services.push.helpers import _order_to_out_dict
        from server.ws.manager import ws_manager
        payload = {
            "type": "ord_cfm",
            "channel": "order_update",
            "ts": datetime.now().isoformat(),
            "data": _order_to_out_dict(order),
        }
        asyncio.ensure_future(ws_manager.broadcast("order_update", payload, trace_id=trace_id))
    except Exception as e:
        log.warning("broadcast_order_cfm failed: %s", e)


__all__ = ["_broadcast_order_cfm"]
