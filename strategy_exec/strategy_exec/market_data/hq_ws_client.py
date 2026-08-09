"""
strategy_exec.market_data.hq_ws_client — hqserver WebSocket 客户端 (Phase 2 仅占位)

📌 Phase 2 简化: 直接在 engines/backtrader/live.py 内 websockets.connect
   本文件为未来统一封装 (订阅多标的, 订阅 cancel, 限速) 留位
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Callable, Optional

import websockets

from strategy_exec.config import get_settings

log = logging.getLogger(__name__)


async def connect_hq_ws(
    on_message: Callable[[dict], None],
    subscribe_codes: Optional[list] = None,
) -> None:
    """连接 hqserver, 订阅 stock_codes, 收 message → on_message(dict)

    永不返回 (除非 on_message 抛异常或 ws 断连) — 在 event loop 内持续运行
    """
    settings = get_settings()
    async with websockets.connect(
        settings.hq_ws_url,
        ping_interval=settings.hq_ws_heartbeat_interval,
        ping_timeout=settings.hq_ws_heartbeat_interval * 2,
    ) as ws:
        if subscribe_codes:
            await ws.send(json.dumps({"type": "subscribe", "stock_codes": subscribe_codes}))
            log.info("[hq_ws] subscribed: %s", subscribe_codes)
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            on_message(msg)