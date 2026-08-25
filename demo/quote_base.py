#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
examples/quote_base.py

纯行情订阅基类 —— 只负责 WS 连接 + 消息分发 + 回调触发。
不登录、不下单、不查持仓。token 由外部注入(从 TradeBase.token 拿)。

用法:
    from quote_base import QuoteBase

    def on_tick(d): print(d["stock_code"], d["last_price"])

    qb = QuoteBase(
        base_url="http://127.0.0.1:8000",
        token="eyJhbGc...",          # 外部登录后注入
        codes=["600519.SH"],
        on_quote=on_tick,
    )
    qb.run()                        # 阻塞;Ctrl+C / qb.stop() 退出
"""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
from typing import Callable, Iterable, Optional, Union

import websockets

log = logging.getLogger("quote_base")

SyncOrAsync = Callable[..., Union[None, "asyncio.Future"]]


class QuoteBase:
    """WS 行情订阅基类。token 外部注入,自己不登录。"""

    def __init__(
        self,
        base_url: str,
        token: str,
        codes: Iterable[str],
        on_quote: Optional[SyncOrAsync] = None,
        on_order: Optional[SyncOrAsync] = None,
        on_trade: Optional[SyncOrAsync] = None,
        on_stop: Optional[SyncOrAsync] = None,
        on_error: Optional[SyncOrAsync] = None,
        ping_interval: int = 25,
    ):
        self.base_url = base_url.rstrip("/")
        self._ws_token = token
        self.codes = list(codes)
        self.ping_interval = ping_interval
        self._on_quote = on_quote
        self._on_order = on_order
        self._on_trade = on_trade
        self._on_stop = on_stop
        self._on_error = on_error
        self._ws = None
        self._stopped = False

    # ──────────── 生命周期 ────────────
    def run(self) -> None:
        """阻塞入口:建 WS → 订阅 → 持续收 push。"""
        try:
            asyncio.run(self._run_loop())
        except KeyboardInterrupt:
            self._fire(self._on_stop, "keyboard_interrupt")

    async def stop(self) -> None:
        """外部主动停。"""
        self._stopped = True
        if self._ws:
            await self._ws.close()

    # ──────────── 私有:WS 主循环 ────────────
    async def _run_loop(self) -> None:
        ws_base = self.base_url.replace("https://", "wss://").replace("http://", "ws://")
        url = f"{ws_base}/ws/quote_update?token={self._ws_token}"
        log.info("🛰  连接 %s", url.split("?")[0] + "?token=***")
        try:
            async with websockets.connect(url, ping_interval=None) as ws:
                self._ws = ws
                log.info("🟢 WS 已建立")
                await ws.send(json.dumps({"type": "subscribe", "stock_codes": self.codes}))
                log.info("📨 subscribe: %s", self.codes)
                await self._recv_loop(ws)
                reason = "stopped" if self._stopped else "ws_closed"
        except websockets.ConnectionClosed as e:
            reason = f"ws_closed: {e}"
            log.warning("⚠️  %s", reason)
            self._fire(self._on_error, e)
        except Exception as e:  # noqa: BLE001
            reason = f"error: {e}"
            log.exception("💥 %s", e)
            self._fire(self._on_error, e)
        finally:
            self._fire(self._on_stop, reason)

    async def _recv_loop(self, ws) -> None:
        last_ping = time.time()
        while not self._stopped:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=self.ping_interval)
            except asyncio.TimeoutError:
                await ws.send(json.dumps({"type": "ping"}))
                last_ping = time.time()
                continue
            await self._dispatch(json.loads(raw))
            if time.time() - last_ping >= self.ping_interval:
                await ws.send(json.dumps({"type": "ping"}))
                last_ping = time.time()

    async def _dispatch(self, msg: dict) -> None:
        mtype = msg.get("type")
        data = msg.get("data") or {}
        if mtype == "quote_update":
            self._fire(self._on_quote, data)
        elif mtype == "quote_batch":
            # v131: 后端把 N 条 tick 装 1 个 ws frame,逐个拆出后走 on_quote
            ticks = data.get("ticks") or []
            log.debug("📦 quote_batch: %d ticks", len(ticks))
            for t in ticks:
                self._fire(self._on_quote, t)
        elif mtype == "ord_cfm":
            self._fire(self._on_order, data)
        elif mtype == "trd_cfm":
            self._fire(self._on_trade, data)
        elif mtype == "subscribe_ack":
            log.info("✅ subscribe_ack: %d 快照", len(msg.get("snapshots") or {}))
        elif mtype in ("ping", "pong"):
            log.debug("💗 %s", mtype)
        else:
            log.warning("⚠️ 未知 type=%s", mtype)

    # ──────────── 私有:同步/异步回调统一 ────────────
    @staticmethod
    def _fire(cb: Optional[SyncOrAsync], *args) -> None:
        if cb is None:
            return
        try:
            r = cb(*args)
            if inspect.iscoroutine(r):
                try:
                    asyncio.get_running_loop().create_task(r)
                except RuntimeError:
                    asyncio.run(r)
        except Exception:  # noqa: BLE001
            log.exception("回调 %s 抛错", getattr(cb, "__name__", cb))
