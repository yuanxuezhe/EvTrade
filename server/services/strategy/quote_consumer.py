"""
strategy — quote_consumer 后端 WS 客户端（change strategy_trade task 7）

📖 详细 spec：openspec/changes/strategy_trade/specs/strategy/spec.md REQ-STRAT-007
📌 连接 hqserver WebSocket（默认 ws://127.0.0.1:8765），fan-out tick 到 StrategyEngine
📌 hqserver 不支持 subscribe/unsubscribe：单连接收全部 tick，本地按 stock_code 过滤
📌 指数退避重连 1s → 2s → 4s → ... → 30s 上限
📌 60s 无 tick → warn log（不主动重连，连接是活的）
📌 30s 心跳：log 活跃 engine 数 + 累计 tick 数
📌 Singleton 模式（仿 RPClient）：module-level _quote_consumer + get/close 函数
📌 STRATEGY_ENGINE_ENABLED=false 时 quote_consumer 不启动（main.py 守门）
"""
import asyncio
import json
import logging
import time
from typing import Dict, Optional

from server.db import db_session
from server.services.strategy import repository as repo
from server.services.strategy.engine import StrategyEngine
from server.services.strategy.indicators import IndicatorParams

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
        self._engines: Dict[str, StrategyEngine] = {}   # stock_code → engine
        self._engine_id_map: Dict[int, StrategyEngine] = {}  # strategy_id → engine（tracing 用）
        self._latest_price: Dict[str, float] = {}
        self._stop = asyncio.Event()
        self._ws = None
        self._last_tick_ts: Optional[float] = None
        self._tick_count: int = 0

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
                self._ws = await connect(self.url, ping_interval=20, ping_timeout=20)
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
                "[quote_consumer health] engines=%d ticks_total=%d last_tick_age=%.1fs",
                engines, self._tick_count,
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
        """解析 hqserver JSON payload → {stock_code, last_price, volume}

        📌 hqserver 消息格式（hq/hqserver.py:159-169）：
           {"type":"quote","channel":"quote_update",
            "data":{"stock_code":"600519.SH","last_price":1820.5,"fields":[...],"body":"..."}}
        📌 解析失败 / 非 quote_update 类型 → 返 None（静默忽略）
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
        # 注：volume 字段当前 hqserver 不直接提供（fields 里包含原始 gbk 字段）
        return {
            "stock_code": stock_code,
            "last_price": float(last_price),
        }

    async def _fanout_tick(self, tick: dict) -> None:
        """按 stock_code 找 engine，await evaluate_tick"""
        stock_code = tick.get("stock_code")
        engine = self._engines.get(stock_code)
        self._latest_price[stock_code] = tick.get("last_price", 0.0)
        self._last_tick_ts = time.time()
        self._tick_count += 1
        if engine is None:
            return  # 非活跃订阅的标的 → 静默丢弃
        # 查 position_vol（v1 简化为 DB 查）
        position_vol = self._get_position_for_stock(stock_code)
        base_volume = engine.last_regime.base_volume if engine.last_regime else None
        # 从 strategy 行拿 base_volume（更稳）
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

    # ── 引擎加载 ──

    async def _load_engines(self) -> None:
        """从 DB 读 status='active' strategies，为每个 stock_code 建 engine

        📌 同 stock_code 多个 strategy → 各自独立 engine（顺序遍历都执行）
        """
        try:
            with db_session() as db:
                # list_strategies 不带 status 过滤，先全查，再筛 active
                all_strats = repo.list_strategies(db, user_id=None) if False else None
                # 用 SQLAlchemy 直接查更清晰
                from server.services.strategy.models import Strategy
                strats = db.query(Strategy).filter(Strategy.status == "active").all()
                engines = {}
                id_map = {}
                for s in strats:
                    eng = StrategyEngine(
                        strategy_id=s.id,
                        stock_code=s.stock_code,
                        initial_params=IndicatorParams.standard(),  # v1: 标准 preset
                    )
                    engines[s.stock_code] = eng
                    id_map[s.id] = eng
                    # 灌 prev_close
                    prev = self._load_prev_close(db, s.stock_code)
                    if prev is not None:
                        eng.set_prev_close(prev)
                    log.info("quote_consumer loaded strategy id=%s stock=%s prev_close=%s",
                             s.id, s.stock_code, prev)
                self._engines = engines
                self._engine_id_map = id_map
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

    # ── 订阅管理（v1 hqserver 不支持，仅本地字典） ──

    def subscribe_strategy(self, strategy_id: int, stock_code: str) -> None:
        """添加一个 strategy 到活跃集合（API 创建/恢复策略时调）"""
        eng = StrategyEngine(
            strategy_id=strategy_id,
            stock_code=stock_code,
            initial_params=IndicatorParams.standard(),
        )
        if stock_code in self._engines:
            # 同 stock_code 多个 strategy → 顺序遍历（v1 不合并）
            log.info("quote_consumer: stock_code=%s 已存在 engine，追加 strategy_id=%s",
                     stock_code, strategy_id)
        self._engines[stock_code] = eng
        self._engine_id_map[strategy_id] = eng

    def unsubscribe_strategy(self, strategy_id: int) -> None:
        """从活跃集合移除（API 暂停/删除策略时调）"""
        eng = self._engine_id_map.pop(strategy_id, None)
        if eng is None:
            return
        # 注意：同 stock_code 多个 strategy 时只移除特定 id 的引用
        if self._engines.get(eng.stock_code) is eng:
            del self._engines[eng.stock_code]


# ─────────────── Module-level singleton（仿 RPClient 模式） ───────────────


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