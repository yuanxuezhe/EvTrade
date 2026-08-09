"""
strategy_exec.engines.backtrader.adapter — ProjectStrategy 基类

📌 用户脚本继承 ProjectStrategy (而非直接 bt.Strategy):
- buy_signal() / sell_signal()  → 推送 RabbitMQ → EvTrade 下单
- notify_signal_published()    → 可选回调 (signal 推送成功/失败)
- get_position()               → 查本地持仓 (Backtrader broker position)

ProjectStrategy 是 bt.Strategy 子类 — Backtrader 正常 next()/init() 仍可用
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

import backtrader as bt

from strategy_exec.signal.publisher import SignalPublishError, get_publisher
from strategy_exec.signal.types import Signal, SignalType

log = logging.getLogger(__name__)


class ProjectStrategy(bt.Strategy):
    """项目用户脚本基类 (继承 bt.Strategy, 提供 buy_signal/sell_signal)"""

    # 由 Engine 在 addstrategy 前注入
    _task_id: int = 0
    _user_id: int = 0
    _script_id: str = ""

    def _set_task_meta(self, task_id: int, user_id: int, script_id: str) -> None:
        """Engine 调用: 注入 task 元数据"""
        self._task_id = task_id
        self._user_id = user_id
        self._script_id = script_id

    def buy_signal(
        self,
        price: float,
        volume: int,
        *,
        price_type: str = "limit",
        indicators: Optional[Dict[str, Any]] = None,
        msg: str = "",
    ) -> Optional[str]:
        """推送 BUY signal. 成功返 trace_id, 失败返 None"""
        return self._publish(SignalType.BUY, price, volume, price_type, indicators, msg)

    def sell_signal(
        self,
        price: float,
        volume: int,
        *,
        price_type: str = "limit",
        indicators: Optional[Dict[str, Any]] = None,
        msg: str = "",
    ) -> Optional[str]:
        """推送 SELL signal. 成功返 trace_id, 失败返 None"""
        return self._publish(SignalType.SELL, price, volume, price_type, indicators, msg)

    def _publish(
        self,
        signal_type: SignalType,
        price: float,
        volume: int,
        price_type: str,
        indicators: Optional[Dict[str, Any]],
        msg: str,
    ) -> Optional[str]:
        """推送 1 条 signal (内部)"""
        if self._task_id == 0:
            log.error("ProjectStrategy 元数据未注入, _task_id=0")
            return None

        signal = Signal(
            task_id=self._task_id,
            user_id=self._user_id,
            script_id=self._script_id,
            signal_type=signal_type,
            stock_code=str(self.data._name),
            price=float(price),
            volume=int(volume),
            price_type=price_type,
            indicators=indicators or {},
            msg=msg,
        )

        try:
            # signal_publisher 是 async, Backtrader next() 是 sync → 跨线程投
            coro = get_publisher().publish_signal(signal)
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # 已在 event loop 内 — schedule (fire-and-forget)
                    future = asyncio.run_coroutine_threadsafe(coro, loop)
                    trace_id = future.result(timeout=10)
                else:
                    trace_id = loop.run_until_complete(coro)
            except RuntimeError:
                # 无 event loop — 新建
                trace_id = asyncio.run(coro)

            log.info(
                "[task:%d] %s signal published: stock=%s price=%.2f vol=%d trace=%s",
                self._task_id, signal_type.value, signal.stock_code,
                price, volume, trace_id,
            )
            self.notify_signal_published(trace_id, ok=True)
            return trace_id
        except SignalPublishError as e:
            log.error("[task:%d] signal publish failed: %s", self._task_id, e)
            self.notify_signal_published("", ok=False)
            return None

    def notify_signal_published(self, signal_id: str, ok: bool) -> None:
        """可选回调 — 用户脚本可 override

        默认: log 一行. 用户 override 可写更复杂逻辑 (如记录 audit)
        """
        if not ok:
            log.warning("[task:%d] signal publish failed, check RabbitMQ", self._task_id)

    def get_position(self) -> int:
        """查当前持仓 (Backtrader broker position)"""
        return self.position.size if self.position else 0

    def get_cash(self) -> float:
        """查当前现金 (Backtrader broker cash)"""
        return self.broker.getcash() if self.broker else 0.0