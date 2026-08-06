"""
server/strategy/runtime/live.py — 实盘引擎 (LiveRunner)

📌 生命周期:
    1. 启动: script_live_runner_manager.start(task_id) → new LiveRunner
    2. 连接 hqserver WebSocket, 订阅 stock_code tick
    3. 收到 tick → 累积 1m K 线 (周期内首根 tick → 新 bar) → 调 on_tick(ctx, tick)
    4. K 线完成 (60s 跨分钟) → 调 on_bar(ctx, bar)
    5. 用户脚本调 doorder → 走 _LiveTradingFacade → server.api.orders.ord_stk

📌 与回测的区别:
- 不需要遍历历史; 接收实时 tick
- 维护 K 线 buffer (1 分钟聚合, 类似 iquant demo 的 row 累积)
- 单 LiveRunner 一个 asyncio task; 用 Singleton manager 管理所有 live runners

📌 停止:
- 手动 stop: manager.stop(task_id) → runner._stop.set() → ws.close()
- 异常: ws 断连 → 自动重连 (指数退避, 同 quote_consumer)
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Set

from server.strategy.lib import make_trading_facade, SignalRecorder
from server.strategy.runtime.sandbox import load_script, SandboxError

log = logging.getLogger(__name__)


# hqserver 默认地址 (同 quote_consumer)
HQ_WS_URL = "ws://127.0.0.1:8765"


# LiveRunner flush 信号到 DB 的间隔 (避免每 tick 写一次)
LIVE_SIGNAL_FLUSH_INTERVAL = 5.0
LIVE_SIGNAL_BUFFER_MAX = 500  # 内存中最多保留条数, 超限丢最早的


# ─────────────── K 线聚合器 ───────────────


class _BarAggregator:
    """把 tick 聚合成 1m K 线

    tick: {"stime": "HHMMSS", "lastPrice": float, "open": float, "high": float, "low": float,
           "volume": int, ...}
    bar:  {"stime": "YYYYMMDDHHMM", "open/high/low/close": float, "volume": int}

    每根 tick 的分钟与当前 bar 一致 → 累加 high/low/volume, close 更新
    跨分钟 → 关闭当前 bar (yield), 开启新 bar
    """

    def __init__(self) -> None:
        self._current: Optional[Dict[str, Any]] = None
        self._last_trd_date: Optional[str] = None  # YYYYMMDD

    def _stime_to_minute(self, trd_date: str, stime_hms: str) -> str:
        """YYYYMMDD + HHMMSS → YYYYMMDDHHMM"""
        hms = stime_hms[:6].ljust(6, "0") if len(stime_hms) >= 6 else stime_hms.ljust(6, "0")
        return f"{trd_date}{hms[:4]}00"

    def on_tick(self, tick: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """推一个 tick, 返回刚关闭的 bar (None 表示还没关闭过)"""
        last = tick.get("lastPrice") or tick.get("last_price")
        if last is None:
            return None
        try:
            last_f = float(last)
        except (TypeError, ValueError):
            return None

        stime = tick.get("stime", "")
        # stime 可能是 "HHMMSS" 或 "HHMMSSfff"; 我们用前 6 位
        hms = stime[:6] if len(stime) >= 6 else stime.ljust(6, "0")
        trd_date = tick.get("trd_date", "")
        if not trd_date:
            # 退化: 用今天日期
            from datetime import datetime
            trd_date = datetime.now().strftime("%Y%m%d")
        minute_key = self._stime_to_minute(trd_date, hms)

        completed_bar: Optional[Dict[str, Any]] = None
        if self._current is not None and self._current["stime"] != minute_key:
            completed_bar = self._current
            self._current = None

        if self._current is None:
            self._current = {
                "stime": minute_key,
                "open": last_f,
                "high": last_f,
                "low": last_f,
                "close": last_f,
                "volume": int(tick.get("volume", 0) or 0),
                "amount": float(tick.get("amount", 0) or 0),
            }
            self._last_trd_date = trd_date
        else:
            self._current["high"] = max(self._current["high"], last_f)
            self._current["low"] = min(self._current["low"], last_f)
            self._current["close"] = last_f
            tick_vol = int(tick.get("volume", 0) or 0)
            tick_amt = float(tick.get("amount", 0) or 0)
            # Handle cumulative volume from broker: if tick volume > current bar volume,
            # treat as cumulative and take the delta; otherwise accumulate incrementally
            if tick_vol >= self._current["volume"]:
                self._current["volume"] = tick_vol
            else:
                self._current["volume"] += tick_vol
            if tick_amt >= self._current["amount"]:
                self._current["amount"] = tick_amt
            else:
                self._current["amount"] += tick_amt

        return completed_bar


# ─────────────── LiveRunner ───────────────


class LiveRunner:
    """单任务的实盘 runner

    Args:
        task_id: strategy_task.id
        script_code: 用户脚本源码
        params: 实际参数值 (e.g. 回测 best_params)
        stock_code: 标的
        loop: 主事件循环 (供 doorder 投 RPC)
    """

    RECONNECT_INITIAL = 1.0
    RECONNECT_MAX = 30.0

    def __init__(
        self,
        task_id: int,
        script_code: str,
        params: Dict[str, Any],
        stock_code: str,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        user_id: Optional[int] = None,
    ) -> None:
        self.task_id = task_id
        self.user_id = user_id
        self.script_code = script_code
        self.params = params
        self.stock_code = stock_code
        self._loop = loop  # 用于 lib facade 异步 RPC
        # v91.6: 订阅的标的集合 (主标的 + 用户脚本 doorder 后扩展)
        # 后端 quote_consumer 按订阅过滤 tick, LiveRunner 只收到这些标的的 tick
        self._subscribed_codes: Set[str] = {stock_code}

        self._stop = asyncio.Event()
        self._ws = None
        self._bar_agg = _BarAggregator()
        # v91.6: 所有订阅标的的最新 tick 缓存 (key=stock_code)
        #   用户脚本做 T 时可 ctx["latest_ticks"].get("B.SH") 查持仓标的行情
        self._latest_ticks: Dict[str, Dict[str, Any]] = {}
        # ws 连接引用 (供动态 subscribe 用)
        self._ws = None

        self._ctx: Dict[str, Any] = {
            "mode": "live",
            "symbol": stock_code,
            "period": "1m",
            "params": params,
            "bars": [],
            # v91.6: 最新 tick 缓存 + 动态订阅入口
            #   ctx["latest_ticks"][stock_code] → 最新 tick dict
            #   ctx["subscribe_extra"]("B.SH") → 动态订阅 B 的 tick
            "latest_ticks": self._latest_ticks,
            "subscribe_extra": self._subscribe_extra,
            "lib": None,
            "signals": SignalRecorder(),
            "state": {},
            "event_loop": loop,
        }
        self._facade = make_trading_facade(self._ctx)
        self._ctx["lib"] = self._facade

        # v10+: 注入风控守卫 (实盘也需风控)
        from server.strategy.runtime.risk import RiskChecker
        self._risk_checker = RiskChecker(initial_cash=100_000.0)
        self._ctx["_risk_checker"] = self._risk_checker

        self._tick_count = 0
        self._bar_count = 0
        self._error_count = 0
        self._last_tick_ts: Optional[float] = None
        self._last_signal_flush_ts: Optional[float] = None
        self._callbacks: Dict[str, Optional[Callable]] = {}

    @property
    def is_running(self) -> bool:
        return not self._stop.is_set()

    async def start(self) -> None:
        """主循环: 加载脚本 → on_init → 重连循环 + 收 tick + on_tick/on_bar"""
        # 1. 加载脚本
        try:
            cbs = load_script(self.script_code, self._ctx, self.params)
        except SandboxError as e:
            log.error("[LiveRunner %d] sandbox error: %s", self.task_id, e)
            await self._mark_failed(f"sandbox: {e}")
            return
        self._callbacks = cbs

        # 2. on_init
        if cbs["on_init"] is not None:
            try:
                cbs["on_init"](self._ctx)
            except Exception as e:
                log.exception("[LiveRunner %d] on_init failed", self.task_id)
                await self._mark_failed(f"on_init: {e}")
                return

        # 3. 重连循环
        backoff = self.RECONNECT_INITIAL
        while not self._stop.is_set():
            try:
                await self._connect_and_consume(cbs)
                backoff = self.RECONNECT_INITIAL  # 成功连过 → 重置退避
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._error_count += 1
                log.warning("[LiveRunner %d] ws error: %s (retry in %.1fs)",
                            self.task_id, e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(self.RECONNECT_MAX, backoff * 2)

    async def stop(self) -> None:
        """外部停止: 置信号 + 关 ws + 最后 flush 一次信号"""
        log.info("[LiveRunner %d] stop requested", self.task_id)
        self._stop.set()
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
        # on_finish 一次性调
        if self._callbacks.get("on_finish") is not None:
            try:
                self._callbacks["on_finish"](self._ctx)
            except Exception:
                log.exception("[LiveRunner %d] on_finish error (ignored)", self.task_id)
        # 最后 flush 一次
        try:
            self._flush_signals()
        except Exception:
            log.exception("[LiveRunner %d] final flush failed", self.task_id)

    def _flush_signals(self) -> None:
        """把当前 signals 持久化到 strategy_task.live_signals + strategy_script_audit

        简化: 每次 flush 都全量重写 (条数上限 500, 性能足够)
        """
        signals = self._ctx.get("signals")
        if signals is None or not signals.log:
            return
        # 截断条数 (从尾部往前取)
        entries = []
        for e in signals.log[-LIVE_SIGNAL_BUFFER_MAX:]:
            e2 = dict(e)
            e2.setdefault("stime", getattr(signals, "_current_stime", ""))
            entries.append(e2)
        try:
            from server.tables import StrategyTask, StrategyScriptAudit
            import json as _json
            row = StrategyTask.query_one(id=self.task_id)
            if row is not None:
                row["live_signals"] = _json.dumps(entries, ensure_ascii=False)
                row["updated_at"] = _now()
                # 同步 trades_count / pnl
                if signals.log:
                    buys = sum(1 for e in entries if e.get("type") == "BUY")
                    sells = sum(1 for e in entries if e.get("type") == "SELL")
                    row["trades_count"] = buys + sells
                row.update()

            # 🆕 写 audit 表 (增量, 用 _last_audit_idx 记录)
            if not hasattr(self, "_last_audit_idx"):
                self._last_audit_idx = 0
            new_entries = signals.log[self._last_audit_idx:]
            for entry in new_entries:
                t = entry.get("type", "INFO")
                stime = entry.get("stime") or getattr(signals, "_current_stime", "")
                trd_date = stime[:8] if stime else ""
                try:
                    StrategyScriptAudit.add_one({
                        "task_id": self.task_id,
                        "stime": stime,
                        "trd_date": trd_date,
                        "phase": "tick",
                        "trigger_type": t,
                        "stock_code": entry.get("stock_code") or self.stock_code,
                        "price": entry.get("price"),
                        "volume": entry.get("volume"),
                        "indicators": _json.dumps(entry.get("indicators") or {}),
                        "state": _json.dumps(entry.get("state") or {}),
                        "msg": entry.get("msg"),
                        "order_no": entry.get("order_no"),
                        "payload": _json.dumps({}),
                    })
                except Exception as e:
                    log.warning("[LiveRunner %d] _flush_audit 单行失败: %s", self.task_id, e)
            self._last_audit_idx += len(new_entries)

            self._last_signal_flush_ts = time.time()
        except Exception:
            log.exception("[LiveRunner %d] _flush_signals DB write failed", self.task_id)

    # ─────────────── 内部 ───────────────

    async def _connect_and_consume(self, cbs: Dict[str, Optional[Callable]]) -> None:
        import websockets  # websockets 11+ 与 quote_consumer 一致
        # v91.6: 改为连后端 /ws/quote_update 走订阅过滤 (而非直连 hqserver 收全部 tick)
        # 后端 quote_consumer.broadcast_to_stock 按订阅 pattern 过滤, LiveRunner 只收到自己订阅的
        ws_url, headers = self._build_ws_url()
        async with websockets.connect(ws_url, additional_headers=headers,
                                       ping_interval=20, ping_timeout=10) as ws:
            self._ws = ws
            log.info("[LiveRunner %d] connected to %s for %s (subscribed=%s)",
                     self.task_id, ws_url, self.stock_code, self._subscribed_codes)

            # 启动时订阅主标的 (T+1 策略: 持仓标的 → 后续脚本 doorder 时再扩展)
            await ws.send(json.dumps({"type": "subscribe", "stock_codes": list(self._subscribed_codes)}))
            log.info("[LiveRunner %d] subscribed initial: %s", self.task_id, list(self._subscribed_codes))

            async for raw in ws:
                if self._stop.is_set():
                    break
                try:
                    msg = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue
                # msg 格式 (后端 quote_update):
                # {"type": "quote", "channel": "quote_update",
                #  "data": {"snapshot": {23 字段}, "fields": [...], "stock_code": "..."}}
                # 也可能是 {"type": "subscribe_ack", ...} 或 {"type": "pong"}
                if msg.get("type") == "pong" or msg.get("type") == "subscribe_ack":
                    continue  # 忽略 ack/pong
                self._dispatch(msg, cbs)

    def _build_ws_url(self) -> tuple:
        """构造 ws URL + headers (含内部 JWT token)

        LiveRunner 内部生成 user token, 连后端 /ws/quote_update 走订阅.
        同进程回环 (127.0.0.1) 走 host header 自动 dispatch 到 FastAPI.
        """
        from server.config import settings
        from server.auth.security import create_access_token as create_token
        # 内部 token: 复用 task.user_id 身份, 走 quote_update 频道 (普通用户可用)
        if self.user_id is None:
            raise RuntimeError("[LiveRunner %d] 缺 user_id, 无法生成内部 token" % self.task_id)
        token = create_token({"sub": str(self.user_id), "id": self.user_id, "role": "user"})
        # 同进程回环: API_HOST 是 0.0.0.0 → ws 用 127.0.0.1
        ws_host = "127.0.0.1" if settings.API_HOST in ("0.0.0.0", "::") else settings.API_HOST
        url = f"ws://{ws_host}:{settings.API_PORT}/ws/quote_update?token={token}"
        return url, {}

    def _subscribe_extra(self, stock_code: str) -> None:
        """T+1 策略做 T 时, 动态订阅新标的

        用户脚本 doorder 触发 buy 后, sandbox facade 检测持仓变化 + 调此方法.
        后端 quote_consumer 收到 subscribe → 后续推此标的 tick 给 LiveRunner.
        """
        if stock_code in self._subscribed_codes:
            return
        self._subscribed_codes.add(stock_code)
        if self._ws is not None:
            try:
                asyncio.run_coroutine_threadsafe(
                    self._ws.send(json.dumps({"type": "subscribe", "stock_codes": [stock_code]})),
                    self._loop,
                )
                log.info("[LiveRunner %d] dynamic subscribe: %s", self.task_id, stock_code)
            except Exception as e:
                log.warning("[LiveRunner %d] dynamic subscribe %s 失败: %s", self.task_id, stock_code, e)

    def _dispatch(self, msg: Dict[str, Any], cbs: Dict[str, Optional[Callable]]) -> None:
        # 解出 tick dict
        data = msg.get("data") or msg
        # v91.6: 后端 quote_consumer 已按订阅过滤 tick, 这里直接解字段
        fields = data.get("fields")
        stock_code = data.get("stock_code")
        snapshot = data.get("snapshot")  # 后端 quote_consumer 推的 23 字段快照
        if fields and isinstance(fields, list):
            tick = _fields_to_tick_dict(stock_code, fields)
            if snapshot:
                tick["snapshot"] = snapshot  # 保留完整快照供脚本用
        elif snapshot and isinstance(snapshot, dict):
            tick = {"stock_code": stock_code, **snapshot}
        elif isinstance(data, dict) and "lastPrice" in data:
            tick = data
        else:
            return

        sc = tick.get("stock_code") or stock_code
        if not sc:
            return

        # v91.6: 缓存所有 tick 到 _latest_ticks (用户脚本可 ctx["latest_ticks"][sc] 查任意订阅标的)
        if not hasattr(self, "_latest_ticks"):
            self._latest_ticks = {}
        self._latest_ticks[sc] = tick

        # v91.6: 不再过滤 stock_code (后端已过滤), 但非主标的只缓存不触发 on_tick/on_bar
        # 主标的才走 K 线聚合 + on_tick/on_bar; 其他订阅标的 (持仓标的) 只更新 latest_ticks
        if sc != self.stock_code:
            return  # 非主标的: 不调 on_tick/on_bar, 不计 _tick_count

        self._tick_count += 1
        self._last_tick_ts = time.time()

        # 给 signals 标当前 tick 时间, 让用户脚本 signal() 有时间锚点
        signals = self._ctx["signals"]
        signals._current_bar_idx = self._tick_count
        signals._current_stime = tick.get("stime", "")

        # 调 on_tick (同步脚本可能在 event loop 里跑)
        if cbs["on_tick"] is not None:
            try:
                cbs["on_tick"](self._ctx, tick)
            except Exception:
                log.exception("[LiveRunner %d] on_tick error (ignored)", self.task_id)

        # K 线聚合
        bar = self._bar_agg.on_tick(tick)
        if bar is not None:
            signals._current_stime = bar.get("stime", signals._current_stime)
            self._ctx["bars"].append(bar)
            # 限制 bars 长度 (防止内存爆炸)
            if len(self._ctx["bars"]) > 5000:
                self._ctx["bars"] = self._ctx["bars"][-2500:]
            self._bar_count += 1
            if cbs["on_bar"] is not None:
                try:
                    cbs["on_bar"](self._ctx, bar)
                except Exception:
                    log.exception("[LiveRunner %d] on_bar error (ignored)", self.task_id)

        # 信号定期 flush 到 DB (避免每 tick 写库)
        if self._last_signal_flush_ts is None:
            self._last_signal_flush_ts = time.time()
        if time.time() - self._last_signal_flush_ts >= LIVE_SIGNAL_FLUSH_INTERVAL:
            self._flush_signals()

    async def _mark_failed(self, msg: str) -> None:
        """标记 task 失败"""
        try:
            from server.tables import StrategyTask
            row = StrategyTask.query_one(id=self.task_id)
            if row:
                row.status = "failed"
                row.error_msg = msg[:500]
                row.finished_at = _now()
                row.update()
        except Exception:
            log.exception("[LiveRunner %d] _mark_failed DB write failed", self.task_id)


# ─────────────── fields[31] → tick dict ───────────────


def _fields_to_tick_dict(stock_code: Optional[str], fields: List[Any]) -> Dict[str, Any]:
    """hqserver 31 字段 tick → dict

    字段顺序 (来自 iquant/quota.py format_quote):
        0: code, 1: stime, 2: lastPrice, 3: open, 4: high, 5: low, 6: lastClose,
        7: volume, 8: amount, 9: openInt, 10: transactionNum,
        11..15: askPrice[5], 16..20: bidPrice[5],
        21..25: askVol[5], 26..30: bidVol[5]
    """
    def _f(idx):
        try:
            return float(fields[idx]) if idx < len(fields) and fields[idx] not in (None, "") else None
        except (TypeError, ValueError):
            return None
    def _i(idx):
        try:
            return int(float(fields[idx])) if idx < len(fields) and fields[idx] not in (None, "") else 0
        except (TypeError, ValueError):
            return 0

    return {
        "stock_code": stock_code or (fields[0] if len(fields) > 0 else ""),
        "stime": fields[1] if len(fields) > 1 else "",
        "lastPrice": _f(2),
        "open": _f(3),
        "high": _f(4),
        "low": _f(5),
        "lastClose": _f(6),
        "volume": _i(7),
        "amount": _f(8),
    }


# ─────────────── manager ───────────────


def _now():
    from datetime import datetime
    return datetime.now()


# module-level singleton
_active_runners: Dict[int, LiveRunner] = {}
_active_tasks: Dict[int, asyncio.Task] = {}


async def start_live_runner(
    task_id: int,
    script_code: str,
    params: Dict[str, Any],
    stock_code: str,
    user_id: Optional[int] = None,
) -> None:
    """启动一个新的 live runner (后台 task)

    Raises:
        RuntimeError: task_id 已存在
    """
    if task_id in _active_runners:
        raise RuntimeError(f"task_id {task_id} 已在运行")
    loop = asyncio.get_running_loop()
    # v91.6: 传 user_id 让 LiveRunner 生成内部 JWT, 连后端 /ws/quote_update 走订阅
    runner = LiveRunner(task_id, script_code, params, stock_code, loop=loop, user_id=user_id)
    _active_runners[task_id] = runner
    _active_tasks[task_id] = asyncio.create_task(runner.start(), name=f"live-runner-{task_id}")
    log.info("live_runner started: task_id=%d stock=%s", task_id, stock_code)


async def stop_live_runner(task_id: int) -> bool:
    """停止一个 live runner

    Returns:
        True 当 runner 存在并被停止; False 当没找到
    """
    runner = _active_runners.pop(task_id, None)
    task = _active_tasks.pop(task_id, None)
    if runner is None:
        return False
    await runner.stop()
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    log.info("live_runner stopped: task_id=%d", task_id)
    return True


def is_running(task_id: int) -> bool:
    return task_id in _active_runners


def get_running_ids() -> Set[int]:
    return set(_active_runners.keys())


__all__ = [
    "LiveRunner",
    "start_live_runner",
    "stop_live_runner",
    "is_running",
    "get_running_ids",
    "HQ_WS_URL",
]