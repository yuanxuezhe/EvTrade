"""
strategy — quote_consumer 后端 WS 客户端（change strategy_trade task 7）

📖 详细 spec：openspec/changes/strategy_trade/specs/strategy/spec.md REQ-STRAT-007
📌 连接 hqserver WebSocket（默认 ws://127.0.0.1:8765），fan-out tick 到 StrategyEngine
📌 hqserver 不支持 subscribe/unsubscribe：单连接收全部 tick，本地按 stock_code 过滤
📌 指数退避重连 1s → 2s → 4s → ... → 30s 上限
📌 60s 无 tick → warn log（不主动重连，连接是活的）
📌 30s 心跳：log 活跃 engine 数 + 累计 tick 数
📌 Singleton 模式（仿 RPClient）：module-level _quote_consumer + get/close 函数
📌 2026-07-09 quote-always-on：启动由 main.py 无条件触发（与 STRATEGY_ENGINE_ENABLED 解耦）
📌 2026-07-09 quote-snapshot-subscribe：
    - _parse_tick 解全 31 字段 (data.fields 数组)，填 snapshot dict 23 数据列
    - _fanout_tick 加 _save_snapshot 持久化（repo/quote_snapshots.upsert）
    - ws broadcast 的 data 保留原 fields[] + last_price（前端 quote store 不变）
    - health log 加 snapshots_saved 计数
"""
import asyncio
import json
import logging
import time
from typing import Dict, Optional

from server.db import db_session
from server.services.strategy.engine import StrategyEngine
from server.services.strategy.indicators import IndicatorParams
from server.cache.quote_cache import get_quote_cache as _get_quote_cache  # 2026-07-10 quote-cache
from server.ws.manager import ws_manager  # change ws-quote-fanout: 让前端 /ws/quote_update 也能收到 tick

# 2026-07-10 quote-cache: 模块级 cache 单例
quote_cache = _get_quote_cache()

log = logging.getLogger(__name__)


# ─────────────── QuoteConsumer ───────────────


class QuoteConsumer:
    """hqserver → StrategyEngine fan-out

    📌 生命周期：start() → load_engines + connect_loop + consume_loop + health_loop
                 stop() → _stop.set() + ws.close()
    📌 主循环内部用 asyncio.gather 同时跑 consume_loop + health_loop，断连时 gather 自动取消
    """

    # 指数退避参数
    RECONNECT_INITIAL = 1.0
    RECONNECT_MAX = 30.0
    # 健康检查参数
    HEALTH_INTERVAL = 30.0
    NO_TICK_WARN = 60.0

    def __init__(self, url: str):
        self.url = url
        self._engines: Dict[str, StrategyEngine] = {}   # stock_code → engine (general)
        self._engine_id_map: Dict[int, StrategyEngine] = {}  # strategy_id → engine（tracing 用）
        # T0 策略引擎（strategy_id → T0StrategyEngine，独立于 general engines）
        self._t0_engines: Dict[int, "T0StrategyEngine"] = {}
        self._latest_price: Dict[str, float] = {}
        self._stop = asyncio.Event()
        self._ws = None
        self._last_tick_ts: Optional[float] = None
        self._tick_count: int = 0
        # 2026-07-09 quote-snapshot-subscribe: 持久化计数
        self._snapshot_count: int = 0
        self._snapshot_err_count: int = 0

    # ── 生命周期 ──

    async def start(self) -> None:
        """入口：加载 engines + 启动主循环（永久直到 stop）"""
        log.info("quote_consumer starting: url=%s", self.url)
        await self._load_engines()
        # 启动主循环（永久）
        await self._main_loop()

    async def stop(self) -> None:
        """置停止信号 + 关 ws"""
        log.info("quote_consumer stopping...")
        self._stop.set()
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception as e:
                log.warning("ws close error: %s", e)

    # ── 主循环 ──

    async def _main_loop(self) -> None:
        """断连时退避重连，连上后跑 consume + health"""
        while not self._stop.is_set():
            try:
                await self._connect()
                # 连上后同时跑消费 + 健康检查
                await asyncio.gather(
                    self._consume_loop(),
                    self._health_loop(),
                )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("quote consumer loop error: %s, will reconnect", e)
            if not self._stop.is_set():
                await asyncio.sleep(self.RECONNECT_INITIAL)

    async def _connect(self) -> None:
        """指数退避重连（1s → 2s → ... → 30s）"""
        # websockets 库 import（顶层 import 失败时给清晰提示）
        try:
            from websockets.client import connect
        except ImportError:
            log.exception("websockets library not installed (pip install websockets)")
            raise

        delay = self.RECONNECT_INITIAL
        while not self._stop.is_set():
            try:
                # 2026-07-09 fix: ping_interval=15s 主动 ping, ping_timeout=60s 给足行情低谷容错
                # 之前 ping_interval=20, ping_timeout=20 在 tick 短暂停顿时被误判断连(1011)
                self._ws = await connect(self.url, ping_interval=15, ping_timeout=60)
                log.info("quote_consumer connected: %s", self.url)
                return
            except Exception as e:
                log.warning("ws connect failed: %s, retry in %.1fs", e, delay)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    pass
                delay = min(delay * 2, self.RECONNECT_MAX)

    async def _consume_loop(self) -> None:
        """async for msg in self._ws: parse + fan-out"""
        while not self._stop.is_set():
            try:
                raw = await self._ws.recv()
            except Exception as e:
                log.warning("ws recv error: %s", e)
                raise  # 让 _main_loop 走重连
            tick = self._parse_tick(raw)
            if tick is None:
                continue
            await self._fanout_tick(tick)

    async def _health_loop(self) -> None:
        """30s 心跳 + 60s 无 tick 警告"""
        while not self._stop.is_set():
            await asyncio.sleep(self.HEALTH_INTERVAL)
            if self._stop.is_set():
                return
            now = time.time()
            engines = len(self._engines)
            log.info(
                "[quote_consumer health] engines=%d ticks_total=%d snapshots_saved=%d snapshot_errs=%d last_tick_age=%.1fs",
                engines, self._tick_count, self._snapshot_count, self._snapshot_err_count,
                (now - self._last_tick_ts) if self._last_tick_ts else -1.0,
            )
            if self._last_tick_ts and (now - self._last_tick_ts) > self.NO_TICK_WARN:
                log.warning(
                    "[quote_consumer] no tick for %.1fs (engines=%d)",
                    now - self._last_tick_ts, engines,
                )

    # ── Tick 解析 + fan-out ──

    @staticmethod
    def _parse_tick(raw: str) -> Optional[dict]:
        """解析 hqserver JSON payload → {stock_code, last_price, snapshot{23 字段}, fields[], body}

        📌 hqserver 消息格式（hq/hqserver.py:159-169）：
           {"type":"quote","channel":"quote_update",
            "data":{"stock_code":"600519.SH","last_price":1820.5,"fields":[...],"body":"..."}}
        📌 fields 数组 31 字段索引（QMT publisher format_quote + hqserver 透传）：
           [0]  stock_code
           [1]  datetime (yyyyMMddHHmmss.sss)
           [2]  last_price
           [3]  open_price / [4] high_price / [5] low_price / [6] prev_close
           [7]  volume / [8] amount
           [9]  openInt (持仓量) / [10] transactionNum (成交笔数)
           [11..15] ask1_price..ask5_price (卖价递增)
           [16..20] bid1_price..bid5_price (买价递减)
           [21..25] ask1_vol..ask5_vol / [26..30] bid1_vol..bid5_vol
        📌 解析失败 / 非 quote_update 类型 → 返 None（静默忽略）
        📌 2026-07-09 quote-snapshot-subscribe:
           - 解全 31 字段 → snapshot dict（23 数据列，映射 ORM QuoteSnapshot）
           - 保留原 fields[] + body 给前端 ws broadcast（quote store 直接用）
        """
        try:
            msg = json.loads(raw)
        except (ValueError, TypeError):
            return None
        if msg.get("channel") != "quote_update" or msg.get("type") != "quote":
            return None
        data = msg.get("data") or {}
        stock_code = data.get("stock_code")
        last_price = data.get("last_price")
        if not stock_code or last_price is None:
            return None

        # 取 fields（hqserver raw 31 字段）
        fields = data.get("fields") or []
        body = data.get("body") or ""

        # ──── 解 snapshot（23 数据列，缺字段给 0） ────
        def f(idx):
            try:
                return float(fields[idx]) if len(fields) > idx and fields[idx] else 0.0
            except (ValueError, TypeError):
                return 0.0

        def iv(idx):
            """volume / *_vol 取整数"""
            try:
                return int(float(fields[idx])) if len(fields) > idx and fields[idx] else 0
            except (ValueError, TypeError):
                return 0

        snapshot = {
            "stock_code": stock_code,
            "last_price": float(last_price),
            "open_price": f(3),
            "high_price": f(4),
            "low_price": f(5),
            "prev_close": f(6),
            "volume": iv(7),
            "amount": f(8),
            "ask1_price": f(11), "ask1_vol": iv(21),
            "ask2_price": f(12), "ask2_vol": iv(22),
            "ask3_price": f(13), "ask3_vol": iv(23),
            "ask4_price": f(14), "ask4_vol": iv(24),
            "ask5_price": f(15), "ask5_vol": iv(25),
            "bid1_price": f(16), "bid1_vol": iv(26),
            "bid2_price": f(17), "bid2_vol": iv(27),
            "bid3_price": f(18), "bid3_vol": iv(28),
            "bid4_price": f(19), "bid4_vol": iv(29),
            "bid5_price": f(20), "bid5_vol": iv(30),
        }

        return {
            "stock_code": stock_code,
            "last_price": float(last_price),
            "snapshot": snapshot,    # 23 字段 dict → _save_snapshot 持久化
            "fields": fields,        # 原 31 字段 → 前端 quote store 用
            "body": body,            # 原 GBK 字符串 → 前端 quote store 用
        }

    async def _fanout_tick(self, tick: dict) -> None:
        """按 stock_code 找 engine，写 cache + 推 ws + evaluate_tick。

        2026-07-10 quote-cache: 之前 await self._save_snapshot(snapshot) 把整个 tick 流
        锁死在 MySQL UPSERT 速率上（实测 ~6/s），导致 ~99% tick 积压。改为
        cache.set(snapshot) 内存 O(1) 写入，持久化由后台 periodic flush task 负责。
        """
        stock_code = tick.get("stock_code")
        snapshot = tick.get("snapshot") or {}
        engine = self._engines.get(stock_code)
        self._latest_price[stock_code] = tick.get("last_price", 0.0)
        self._last_tick_ts = time.time()
        self._tick_count += 1

        # 2026-07-10 quote-cache: 写内存 cache (O(1) dict set + dirty mark)
        #    不再 await MySQL UPSERT，持久化由 periodic flush task 负责
        if snapshot and snapshot.get("stock_code"):
            quote_cache.set(snapshot)

        # 2026-07-09 quote-snapshot-subscribe: 按 stock_code 严格过滤
        #    严格走 broadcast_to_stock 推订阅者，不再 fallback 兼容老前端
        delivered = 0
        try:
            delivered = await ws_manager.broadcast_to_stock(stock_code, {"type": "quote", "channel": "quote_update", "data": tick})
        except Exception:
            log.exception("ws quote broadcast failed (non-fatal)")
        if engine is None and not self._t0_engines:
            return  # 非活跃订阅的标的 → 静默丢弃
        # 查 position_vol（v1 简化为 DB 查）
        position_vol = self._get_position_for_stock(stock_code)

        # 评估 general engine
        if engine is not None:
            base_volume = engine.last_regime.base_volume if engine.last_regime else None
            if base_volume is None:
                base_volume = self._get_base_volume_for_stock(stock_code)
            try:
                await engine.evaluate_tick(
                    tick=tick,
                    position_vol=position_vol,
                    base_volume=base_volume or 0,
                    prev_close=engine.prev_close,
                )
            except Exception as e:
                log.exception("evaluate_tick failed: stock=%s err=%s", stock_code, e)

        # 评估 T0 engines（按 stock_code 匹配）
        for sid, t0_eng in list(self._t0_engines.items()):
            if t0_eng.stock_code != stock_code:
                continue
            base_volume = self._get_base_volume_for_strategy(sid)
            try:
                await t0_eng.evaluate_tick(
                    tick=tick,
                    position_vol=position_vol,
                    base_volume=base_volume or 0,
                    prev_close=t0_eng.prev_close,
                )
            except Exception as e:
                log.exception("T0 evaluate_tick failed: stock=%s strategy=%s err=%s",
                              stock_code, sid, e)

    # ── Snapshot 持久化 ──

    @staticmethod
    async def _save_snapshot(snapshot: dict) -> None:
        """持久化到 quote_snapshots 表（latest-only UPSERT，跨方言）。

        📌 2026-07-09 quote-snapshot-subscribe:
           - 同步阻塞式 ORM 操作包到 to_thread（quote_consumer 跑在 asyncio 事件循环）
           - SQLAlchemy session 默认 sync API，会阻塞事件循环
           - SQLite 单写线程 → 用 to_thread 隔离避免阻塞其他 ws 心跳
        📌 upsert 失败 → 计数 + log，不抛（不影响 tick 流）
        """
        if not snapshot or not snapshot.get("stock_code"):
            return
        from server.repo.quote_snapshots import upsert as _repo_upsert

        def _do_upsert():
            try:
                with db_session() as db:
                    _repo_upsert(db, snapshot)
                    db.commit()
                # 成功后递增计数（绕过线程隔离直接走实例属性）
                return ("ok", None)
            except Exception as e:
                return ("err", str(e))

        try:
            status, msg = await asyncio.to_thread(_do_upsert)
            if status == "ok":
                # 安全递增计数（实例属性，asyncio 协程内）
                inst = _active_consumer()
                if inst is not None:
                    inst._snapshot_count += 1
            else:
                inst = _active_consumer()
                if inst is not None:
                    inst._snapshot_err_count += 1
                log.warning("quote_snapshot upsert failed: stock=%s err=%s",
                            snapshot.get("stock_code"), msg)
        except Exception:
            log.exception("quote_snapshot save unexpected error")

    # ── 引擎加载 ──

    async def _load_engines(self) -> None:
        """从 DB 读 status='active' strategies，为每个 stock_code 建 engine

        📌 同 stock_code 多个 strategy → 各自独立 engine（顺序遍历都执行）
        📌 type='t0' → T0StrategyEngine；type='general' → StrategyEngine
        """
        try:
            with db_session() as db:
                from server.services.strategy.models import Strategy
                strats = db.query(Strategy).filter(Strategy.status == "active").all()
                engines = {}
                id_map = {}
                t0_engines = {}
                for s in strats:
                    if s.type == "t0":
                        from server.services.strategy.t0.engine import T0StrategyEngine
                        from server.services.strategy.t0.models import T0StrategyParams
                        t0_params = T0StrategyParams.from_json(s.t0_params) if s.t0_params else T0StrategyParams()
                        eng = T0StrategyEngine(
                            strategy_id=s.id,
                            stock_code=s.stock_code,
                            initial_params=t0_params,
                        )
                        t0_engines[s.id] = eng
                    else:
                        eng = StrategyEngine(
                            strategy_id=s.id,
                            stock_code=s.stock_code,
                            initial_params=IndicatorParams.standard(),
                        )
                        engines[s.stock_code] = eng
                        id_map[s.id] = eng

                    prev = self._load_prev_close(db, s.stock_code)
                    if prev is not None:
                        eng.set_prev_close(prev)
                    log.info("quote_consumer loaded strategy id=%s stock=%s type=%s prev_close=%s",
                             s.id, s.stock_code, s.type, prev)
                self._engines = engines
                self._engine_id_map = id_map
                self._t0_engines = t0_engines
        except Exception as e:
            log.exception("load_engines failed: %s", e)

    @staticmethod
    def _load_prev_close(db, stock_code: str) -> Optional[float]:
        """从 QuoteSnapshot 表读最近一条 snapshot 的 prev_close"""
        try:
            from server.models.orm import QuoteSnapshot
            snap = db.query(QuoteSnapshot).filter(
                QuoteSnapshot.stock_code == stock_code,
                QuoteSnapshot.prev_close > 0,
            ).order_by(QuoteSnapshot.ts.desc()).first()
            if snap:
                return float(snap.prev_close)
        except Exception:
            pass
        return None

    # ── 持仓查询（v1 简化为 DB 查） ──

    @staticmethod
    def _get_position_for_stock(stock_code: str) -> int:
        """查 stock_code 的当前持仓（v1 简化为从 Trade 表累计）

        📌 真实实现后续可优化为本地缓存 + ws trd_cfm 增量更新
        📌 当前 fallback：返 0（让 engine 按无持仓评估，不下卖单）
        """
        try:
            with db_session() as db:
                # Trade 表累计成交量（按 direction 折算净持仓）
                # 简化：BUY - SELL 累计，未做 T+1 拆分（task 8 / v2 强化）
                from sqlalchemy import text
                result = db.execute(text("""
                    SELECT
                        COALESCE(SUM(CASE WHEN direction='BUY' THEN volume ELSE 0 END), 0)
                        - COALESCE(SUM(CASE WHEN direction='SELL' THEN volume ELSE 0 END), 0)
                    FROM trades
                    WHERE stock_code = :code
                """), {"code": stock_code}).scalar()
                return int(result or 0)
        except Exception:
            return 0

    @staticmethod
    def _get_base_volume_for_stock(stock_code: str) -> int:
        """查 stock_code 对应 active strategy 的 base_volume（v1 取第一个匹配）"""
        try:
            with db_session() as db:
                from server.services.strategy.models import Strategy
                s = db.query(Strategy).filter(
                    Strategy.stock_code == stock_code,
                    Strategy.status == "active",
                ).first()
                return int(s.base_volume) if s else 0
        except Exception:
            return 0

    @staticmethod
    def _get_base_volume_for_strategy(strategy_id: int) -> int:
        """查 strategy_id 对应的 base_volume（T0 引擎用）"""
        try:
            with db_session() as db:
                from server.services.strategy.models import Strategy
                s = db.query(Strategy).filter(Strategy.id == strategy_id).first()
                return int(s.base_volume) if s else 0
        except Exception:
            return 0

    # ── 订阅管理（v1 hqserver 不支持，仅本地字典） ──

    def subscribe_strategy(self, strategy_id: int, stock_code: str,
                           strategy_type: str = "general") -> None:
        """添加一个 strategy 到活跃集合（API 创建/恢复策略时调）"""
        if strategy_type == "t0":
            from server.services.strategy.t0.engine import T0StrategyEngine
            from server.services.strategy.t0.models import T0StrategyParams
            eng = T0StrategyEngine(
                strategy_id=strategy_id,
                stock_code=stock_code,
                initial_params=T0StrategyParams(),
            )
            self._t0_engines[strategy_id] = eng
            log.info("quote_consumer: T0 subscribe strategy_id=%s stock=%s",
                     strategy_id, stock_code)
        else:
            eng = StrategyEngine(
                strategy_id=strategy_id,
                stock_code=stock_code,
                initial_params=IndicatorParams.standard(),
            )
            if stock_code in self._engines:
                log.info("quote_consumer: stock_code=%s 已存在 engine，追加 strategy_id=%s",
                         stock_code, strategy_id)
            self._engines[stock_code] = eng
            self._engine_id_map[strategy_id] = eng

    def unsubscribe_strategy(self, strategy_id: int) -> None:
        """从活跃集合移除（API 暂停/删除策略时调）"""
        # 检查 T0 engines
        t0_eng = self._t0_engines.pop(strategy_id, None)
        if t0_eng is not None:
            log.info("quote_consumer: T0 unsubscribe strategy_id=%s", strategy_id)
            return

        # general engines
        eng = self._engine_id_map.pop(strategy_id, None)
        if eng is None:
            return
        if self._engines.get(eng.stock_code) is eng:
            del self._engines[eng.stock_code]


# ─────────────── Module-level singleton（仿 RPClient 模式） ───────────────


def _active_consumer() -> Optional["QuoteConsumer"]:
    """获取当前活跃 singleton 实例（_save_snapshot 在 to_thread 中拿不到 self）

    📌 2026-07-09 quote-snapshot-subscribe:
       - to_thread 内无法捕获 self（asyncio 协程跨线程安全）
       - 提供 module-level getter 让 _save_snapshot 找到当前 consumer 累加计数
    """
    return _quote_consumer


_quote_consumer: Optional[QuoteConsumer] = None


async def get_quote_consumer() -> QuoteConsumer:
    """获取或创建 QuoteConsumer singleton（main.py startup 调用）"""
    global _quote_consumer
    if _quote_consumer is None:
        from server.config import settings
        qc = QuoteConsumer(url=settings.HQ_WS_URL)
        _quote_consumer = qc
        # 不 await start()，让它跑后台 task
        asyncio.ensure_future(qc.start())
    return _quote_consumer


async def close_quote_consumer() -> None:
    """停止 QuoteConsumer（main.py shutdown 调用）"""
    global _quote_consumer
    if _quote_consumer is not None:
        await _quote_consumer.stop()
        _quote_consumer = None


__all__ = ["QuoteConsumer", "get_quote_consumer", "close_quote_consumer"]