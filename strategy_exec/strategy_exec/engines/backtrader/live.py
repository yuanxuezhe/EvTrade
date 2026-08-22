"""
strategy_exec.engines.backtrader.live — Backtrader 实盘引擎

📌 流程:
1. 读 strategy_script.code + 用户元数据
2. sandbox loader 加载 ProjectStrategy 子类
3. 启动 asyncio task: 订阅 hqserver WS → 累积 K 线 → 调 next()
4. next() 触发 buy/sell_signal → signal_publisher.publish_signal() (推送 RabbitMQ)

特点:
- 单 LiveRunner 一个 asyncio task
- manager 单例管理所有 live runners (按 task_id)
- WS 断线自动重连 (指数退避, 同 quote_consumer)
- 停止: manager.stop(task_id) → 调 cerebro 终止 + 关闭 WS
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional

import websockets
from sqlalchemy import text

from strategy_exec.config import get_settings
from strategy_exec.data_access import (
    append_live_signals, get_script, update_task_progress, update_task_status, write_audit,
)
from strategy_exec.engines.backtrader.adapter import ProjectStrategy
from strategy_exec.sandbox.loader import load_strategy_class

log = logging.getLogger(__name__)


LIVE_SIGNAL_FLUSH_INTERVAL = 5.0
LIVE_SIGNAL_BUFFER_MAX = 500


# ─────────────── K 线聚合器 ───────────────


class _BarAggregator:
    """把 tick 聚合成 1m K 线

    Backtrader 默认每根 bar 调一次 next(), 我们累积 tick 到分钟切换
    """

    def __init__(self) -> None:
        self.current_bar: Optional[Dict[str, Any]] = None
        self.current_minute: Optional[str] = None

    def on_tick(self, tick: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """收 1 个 tick, 完整 1m bar 时返 (否则 None)"""
        # tick: {stime: 'HHMMSS', lastPrice, open, high, low, volume}
        stime = tick.get("stime", "")
        if len(stime) < 4:
            return None
        minute = stime[:4]  # HHMM

        if self.current_minute != minute:
            # 新分钟: 推上一根 (若有)
            finished = self.current_bar if self.current_bar else None
            self.current_minute = minute
            self.current_bar = {
                "stime": stime,
                "open": tick.get("open", tick.get("lastPrice", 0)),
                "high": tick.get("high", tick.get("lastPrice", 0)),
                "low": tick.get("low", tick.get("lastPrice", 0)),
                "close": tick.get("lastPrice", 0),
                "volume": tick.get("volume", 0),
            }
            return finished

        # 同分钟内累积
        if self.current_bar is None:
            return None
        self.current_bar["high"] = max(self.current_bar["high"], tick.get("high", tick.get("lastPrice", 0)))
        self.current_bar["low"] = min(self.current_bar["low"], tick.get("low", tick.get("lastPrice", 0)))
        self.current_bar["close"] = tick.get("lastPrice", 0)
        self.current_bar["volume"] += tick.get("volume", 0)
        return None


# ─────────────── LiveRunner 单实例 ───────────────


class LiveRunner:
    """单 live 任务的 runner

    生命周期: 创建 → connect WS → 收 tick → 调 next() → 停止
    """

    def __init__(
        self,
        task_id: int,
        user_id: int,
        script_id: str,
        stock_code: str,
        params: Dict[str, Any],
        code: str,
        params_schema: Optional[List[Dict[str, Any]]] = None,
        parent_task_id: Optional[int] = None,   # 母单归因
        strategy_name: str = "",                 # 子单 user_def
    ) -> None:
        self.task_id = task_id
        self.user_id = user_id
        self.script_id = script_id
        self.stock_code = stock_code
        self.params = params
        self.code = code
        self.params_schema = params_schema
        self.parent_task_id = parent_task_id
        self.strategy_name = strategy_name

        self.settings = get_settings()
        self._stop_event = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self._ws: Optional[Any] = None
        self._strategy_instance: Optional[ProjectStrategy] = None
        self._bars_buffer: Deque[Dict[str, Any]] = deque(maxlen=10000)
        self._signal_buffer: Deque[Dict[str, Any]] = deque(maxlen=LIVE_SIGNAL_BUFFER_MAX)
        self._last_flush = time.time()
        self._aggregator = _BarAggregator()

    async def start(self) -> None:
        """启动 runner (在 event loop 中)"""
        self._task = asyncio.create_task(self._run(), name=f"live-{self.task_id}")

    async def stop(self) -> None:
        """停止 runner"""
        log.info("[LiveRunner %d] stopping...", self.task_id)
        self._stop_event.set()
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    async def _run(self) -> None:
        """主循环: 连接 WS → 收 tick → 调 next()"""
        # ──── 加载策略 ────
        try:
            strategy_cls = load_strategy_class(self.code, ProjectStrategy, params_schema=self.params_schema)
            # 构造 (无 cerebro, 直接 instantiate)
            # bt.Strategy 需要 cerebro 上下文, 简化: 用临时 cerebro 启动
            import backtrader as bt

            cerebro = bt.Cerebro()
            cerebro.addstrategy(strategy_cls, **self.params)
            # 无 data feed (手工推 next), 用最小 broker
            cerebro.broker.setcash(100000.0)
            # runonce=False + preload=False + run 1 步 (拿到 strategy instance)
            self._strategy_instance = cerebro.run()[0]
            self._strategy_instance._set_task_meta(
                self.task_id, self.user_id, self.script_id, mode="live",
                parent_task_id=self.parent_task_id, strategy_name=self.strategy_name,
            )
        except Exception as e:
            log.error("[LiveRunner %d] strategy load failed: %s", self.task_id, e)
            update_task_status(self.task_id, "failed", error_msg=f"strategy load: {e}")
            return

        update_task_status(self.task_id, "running")

        # ──── 连接 WS (指数退避) ────
        retry_delay = self.settings.hq_ws_reconnect_base_delay / 1000
        while not self._stop_event.is_set():
            try:
                await self._connect_and_consume()
            except Exception as e:
                log.warning("[LiveRunner %d] WS error: %s, retry in %.1fs",
                            self.task_id, e, retry_delay)
                await asyncio.sleep(retry_delay)
                retry_delay = min(
                    retry_delay * 2,
                    self.settings.hq_ws_reconnect_max_delay / 1000,
                )
                continue
            retry_delay = self.settings.hq_ws_reconnect_base_delay / 1000

    async def _connect_and_consume(self) -> None:
        """连 WS, 订阅 stock_code, 收 tick → 调 next()"""
        async with websockets.connect(
            self.settings.hq_ws_url,
            ping_interval=self.settings.hq_ws_heartbeat_interval,
            ping_timeout=self.settings.hq_ws_heartbeat_interval * 2,
        ) as ws:
            self._ws = ws
            # subscribe
            await ws.send(json.dumps({
                "type": "subscribe",
                "stock_codes": [self.stock_code],
            }))
            log.info("[LiveRunner %d] connected to %s, subscribed=%s",
                     self.task_id, self.settings.hq_ws_url, self.stock_code)

            update_task_progress(self.task_id, {
                "phase": "live", "current": 1, "total": 1,
                "msg": f"订阅 {self.stock_code} tick 中...",
            })

            # 收 tick
            async for raw in ws:
                if self._stop_event.is_set():
                    break
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if msg.get("type") != "quote":
                    continue
                data = msg.get("data") or msg
                if data.get("code") != self.stock_code and data.get("stock_code") != self.stock_code:
                    continue
                await self._on_tick(data)

    async def _on_tick(self, tick: Dict[str, Any]) -> None:
        """收 1 tick, 累积 bar + 调 next()"""
        finished_bar = self._aggregator.on_tick(tick)
        if finished_bar is None:
            return

        # 调 next() (在 sandbox 内 — user 脚本逻辑)
        try:
            if self._strategy_instance is None:
                return
            # Backtrader next() 是 sync — 直接调 (event loop 内同步代码允许)
            self._strategy_instance.next()
        except Exception as e:
            log.error("[LiveRunner %d] next() failed: %s", self.task_id, e)
            update_task_status(self.task_id, "failed", error_msg=f"next() exception: {e}")
            self._stop_event.set()
            return

        # 写 audit + append live_signals (兜底 — ProjectStrategy 推送 signal 已写)
        # 这里仅记录进度 + 周期性 flush 信号到 DB
        now = time.time()
        if now - self._last_flush >= LIVE_SIGNAL_FLUSH_INTERVAL:
            self._last_flush = now
            # flush self._signal_buffer → strategy_task.live_signals
            if self._signal_buffer:
                try:
                    append_live_signals(self.task_id, list(self._signal_buffer))
                    self._signal_buffer.clear()
                except Exception as e:
                    log.warning("[LiveRunner %d] flush signals failed: %s", self.task_id, e)
            # progress
            update_task_progress(self.task_id, {
                "phase": "live_running",
                "msg": f"运行中, 最近 bar={finished_bar.get('stime', '?')}",
            })


# ─────────────── Manager 单例 ───────────────


class _LiveRunnerManager:
    """所有 live runners 注册表 (按 task_id)"""

    def __init__(self) -> None:
        self._runners: Dict[int, LiveRunner] = {}

    def start_runner(self, runner: LiveRunner) -> None:
        self._runners[runner.task_id] = runner

    async def stop_runner(self, task_id: int) -> bool:
        runner = self._runners.pop(task_id, None)
        if runner is None:
            return False
        await runner.stop()
        return True

    def is_running(self, task_id: int) -> bool:
        return task_id in self._runners

    async def stop_all(self) -> None:
        for task_id in list(self._runners.keys()):
            await self.stop_runner(task_id)


_manager = _LiveRunnerManager()


def get_live_manager() -> _LiveRunnerManager:
    return _manager


async def start_live_runner(
    task_id: int,
    user_id: int,
    script_id: str,
    stock_code: str,
    params: Dict[str, Any],
    parent_task_id: Optional[int] = None,   # 母单归因
    strategy_name: str = "",                 # 子单 user_def
) -> LiveRunner:
    """启动一个 live runner (EvTrade 转发调)"""
    script_row = get_script(user_id, script_id)
    if script_row is None:
        raise ValueError(f"script not found: ({user_id}, {script_id})")

    runner = LiveRunner(
        task_id=task_id,
        user_id=user_id,
        script_id=script_id,
        stock_code=stock_code,
        params=params,
        code=script_row["code"],
        params_schema=script_row.get("params_schema") or None,
        parent_task_id=parent_task_id,
        strategy_name=strategy_name,
    )
    await runner.start()
    _manager.start_runner(runner)
    log.info("[live] started runner task=%d", task_id)
    return runner


async def stop_live_runner(task_id: int) -> bool:
    return await _manager.stop_runner(task_id)


def is_running(task_id: int) -> bool:
    return _manager.is_running(task_id)


async def stop_all_live_runners() -> None:
    """应用关闭时"""
    await _manager.stop_all()