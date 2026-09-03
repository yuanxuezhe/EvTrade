"""
strategy_exec.market_data.hq_history — 拉历史 K 线 (broker his_hq)

📌 broker his_hq 是 xtquant 的 RabbitMQ 通道:
   - exchange: quota_his.exchange (topic)
   - req_queue: EvTrade.ReqHisHq (broker 监听此队列)
   - 协议: msgpacket 二进制格式 (与 iquant/quota_his_test.py 完全一致)
   - 关键: ans_queue 放在 body 字段里，不是 reply_to header

Strategy_exec 与 EvTrade 共享 broker, 走同一 RabbitMQ URL
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import uuid
from typing import Any, List, Optional

import aio_pika
from aio_pika.abc import AbstractRobustConnection

from strategy_exec.config import get_settings
from strategy_exec.market_data.aggregator import aggregate_bars
from strategy_exec.market_data.his_hq_client import DEFAULT_FIELDS

log = logging.getLogger(__name__)


# ─────────────── change 2026-09-04 sql-aggregated-backtest ───────────────
# broker 1m + 全字段 (OHLCV+amount), 回测拉取后 upsert minute_bars,
# 再用 SQL 按用户 period 聚合查询 (open=首/close=末/high=max/low=min/volume=sum/avg_price=VWAP).
_BROKER_PERIOD = "1m"
_BROKER_FIELDS = DEFAULT_FIELDS


class HQHistoryError(Exception):
    """拉历史 K 线失败"""


def _iter_rows(raw_text: str):
    """Parse broker reply body.

    Wire format:
        <col_header>\\n<row1>|<row2>|...
    where row_i = "<stime>#<field1>#<field2>..."
    """
    header_line, _, body = raw_text.partition("\n")
    columns = header_line.split(",")
    if not body.strip():
        return
    for line in body.split("|"):
        if not line:
            continue
        values = line.split("#")
        yield columns, dict(zip(columns, values))


def _weekdays_in(start: str, end: str) -> int:
    """YYYYMMDD 区间内工作日数 — 服务端按天推送的 reply 条数上界.

    法定节假日/无数据天会被服务端跳过, 因此实际 reply 数 <= 工作日数.
    仅用于日志提示, 不作为截断依据.
    """
    s = datetime.datetime.strptime(start[:8], "%Y%m%d").date()
    e = datetime.datetime.strptime(end[:8], "%Y%m%d").date()
    return sum(
        1
        for i in range((e - s).days + 1)
        if (s + datetime.timedelta(days=i)).weekday() < 5
    )


class HQHistoryClient:
    """async client for broker his_hq (单连接, 复用 channel)

    协议参考: iquant/quota_his_test.py
    - 使用 MsgPacket 二进制格式 (非 JSON)
    - ans_queue 放在 body 字段里
    - ans_queue 用 exclusive auto_delete 临时队列接收 reply
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self._connection: Optional[AbstractRobustConnection] = None
        self._channel: Optional[aio_pika.abc.AbstractRobustChannel] = None

    async def connect(self) -> None:
        if self._connection is not None and not self._connection.is_closed:
            return
        self._connection = await aio_pika.connect_robust(self.settings.evtrade_rabbitmq_url)
        self._channel = await self._connection.channel()
        log.info("[hq_history] connected to %s", self.settings.evtrade_rabbitmq_url)

    async def close(self) -> None:
        if self._connection is not None and not self._connection.is_closed:
            await self._connection.close()
        self._connection = None
        self._channel = None

    async def fetch_bars(
        self,
        stock_code: str,
        start_date: str,  # YYYYMMDD
        end_date: str,    # YYYYMMDD
        period: str = "1d",
        fields: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """拉历史 K 线, 返 list of dict [{stime, open, high, low, close, volume, avg_price}, ...]

        change 2026-09-04-sql-aggregated-backtest:
        - broker 1m + 全字段 (OHLCV+amount) 拉取 → upsert minute_bars
        - 按 period 用 SQL 聚合查询 (open=首/close=末/high=max/low=min/volume=sum/avg_price=VWAP)
        - cache 命中 (full cover): 跳过 broker, 直接 SQL 聚合
        - cache 部分覆盖: 缺天 broker 补 + 写回 → SQL 聚合重查
        - cache 关闭: broker 全拉 + upsert → SQL 聚合重查
        - 所有路径最终都走 query_bars_aggregated (DB 聚合, 六字段全输出)

        change 2026-08-30-his-hq-chunked-fetch:
        - 长区间 (≥30 天) broker 单次 fetch 30s 超时 → 拆 N 段 (默认 10 天/批)
        - 串行调 _fetch_one_chunk() → 拼凑 + sort by stime
        - 任一段 raise → 立即 raise (不返部分数据)
        """
        # ── change 2026-09-04 sql-aggregated-backtest: 先查 minute_bars ──
        if self.settings.his_hq_cache_enabled:
            from strategy_exec.data_access.minute_bars import (
                query_minute_bars, upsert_minute_bars, is_full_cover,
                query_bars_aggregated,
            )
            cached_bars = await query_minute_bars(stock_code, start_date, end_date)
            if cached_bars and is_full_cover(cached_bars, start_date, end_date):
                log.info(
                    "[hq_history] cache FULL HIT: stock=%s %s~%s → %d 1m bars (skip broker)",
                    stock_code, start_date, end_date, len(cached_bars),
                )
                return await query_bars_aggregated(stock_code, start_date, end_date, period)

            if cached_bars:
                log.info(
                    "[hq_history] cache PARTIAL: stock=%s %s~%s → %d bars (need broker for missing)",
                    stock_code, start_date, end_date, len(cached_bars),
                )
            else:
                log.info(
                    "[hq_history] cache MISS: stock=%s %s~%s (need broker)",
                    stock_code, start_date, end_date,
                )
            # 走 chunked fetch (broker + 写回 cache) → 最后 SQL 聚合重查
            await self._chunked_fetch_with_cache(
                stock_code, start_date, end_date, period,
                cached_bars=cached_bars,
                upsert_fn=upsert_minute_bars,
            )
            return await query_bars_aggregated(stock_code, start_date, end_date, period)

        # ── cache 关闭: 走原 chunked fetch 路径 (仍 upsert + SQL 聚合重查) ──
        await self._chunked_fetch_only(stock_code, start_date, end_date, period)
        return await query_bars_aggregated(stock_code, start_date, end_date, period)

    async def _chunked_fetch_with_cache(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
        period: str,
        cached_bars: List[Dict[str, Any]],
        upsert_fn,
    ) -> None:
        """chunked fetch + 部分覆盖场景: cached 已覆盖 + 缺天 broker 补 + 写回.

        change 2026-09-04: 不再做 Python 聚合, 只负责 fetch + upsert.
        聚合由调用方 fetch_bars 统一走 query_bars_aggregated (SQL).
        """
        # chunked_enabled=False → 1 次拉全区间 (向后兼容, 不拆段)
        if not self.settings.his_hq_chunk_enabled:
            log.info(
                "[hq_history] chunked disabled (cache-augmented): stock=%s %s~%s → 1 broker fetch (cache_writeback)",
                stock_code, start_date, end_date,
            )
            try:
                broker_bars = await self._fetch_one_chunk(stock_code, start_date, end_date, period)
            except HQHistoryError as e:
                raise HQHistoryError(f"broker fetch failed: {e}") from e
            if broker_bars:
                try:
                    n = await upsert_fn(stock_code, broker_bars)
                    if n:
                        log.info("[hq_history] cache write-back: stock=%s wrote %d rows (1-shot)",
                                 stock_code, n)
                except Exception as e:  # noqa: BLE001
                    log.warning("[hq_history] cache write-back failed (non-fatal): %s", e)
            return
        chunks = _iter_chunks(start_date, end_date, self.settings.his_hq_chunk_days)
        log.info(
            "[hq_history] chunked fetch (cache-augmented): stock=%s %s~%s → %d chunks (cached=%d bars)",
            stock_code, start_date, end_date, len(chunks), len(cached_bars),
        )
        for i, (cs, ce) in enumerate(chunks, 1):
            # 跳过完全覆盖的 chunk (cached 已有数据)
            if cached_bars and _chunk_fully_cached(cached_bars, cs, ce):
                log.debug(
                    "[hq_history] chunked fetch: chunk %d/%d (%s~%s) FULLY CACHED, skip",
                    i, len(chunks), cs, ce,
                )
                continue
            log.info(
                "[hq_history] chunked fetch: stock=%s chunk %d/%d (%s~%s)",
                stock_code, i, len(chunks), cs, ce,
            )
            try:
                bars_i = await self._fetch_one_chunk(stock_code, cs, ce, period)
            except HQHistoryError as e:
                raise HQHistoryError(
                    f"chunked fetch failed at chunk {i}/{len(chunks)} ({cs}~{ce}): {e}"
                ) from e
            # 写回 minute_bars (broker raw → minute_bars)
            if bars_i:
                try:
                    n = await upsert_fn(stock_code, bars_i)
                    if n:
                        log.info("[hq_history] cache write-back: stock=%s chunk=%d/%d wrote %d rows",
                                 stock_code, i, len(chunks), n)
                except Exception as e:  # noqa: BLE001
                    log.warning("[hq_history] cache write-back failed (non-fatal): %s", e)
        return

    async def _chunked_fetch_only(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
        period: str,
    ) -> None:
        """原 chunked fetch 路径 (cache 关闭时用) — 不查表, 但仍 upsert 落库.

        change 2026-09-04: 不再 Python 聚合返回, 只 fetch + upsert.
        聚合由调用方 fetch_bars 统一走 query_bars_aggregated (SQL).
        """
        from strategy_exec.data_access.minute_bars import upsert_minute_bars

        async def _upsert(bars: List[Dict[str, Any]]) -> int:
            return await upsert_minute_bars(stock_code, bars)

        # ── change 2026-08-30-his-hq-chunked-fetch: chunked 调度 ──
        if self.settings.his_hq_chunk_enabled:
            chunks = _iter_chunks(start_date, end_date, self.settings.his_hq_chunk_days)
            log.info(
                "[hq_history] chunked fetch enabled: stock=%s %s~%s → %d chunks (chunk_days=%d)",
                stock_code, start_date, end_date, len(chunks), self.settings.his_hq_chunk_days,
            )
            for i, (cs, ce) in enumerate(chunks, 1):
                log.info(
                    "[hq_history] chunked fetch: stock=%s chunk %d/%d (%s~%s)",
                    stock_code, i, len(chunks), cs, ce,
                )
                try:
                    bars_i = await self._fetch_one_chunk(stock_code, cs, ce, period)
                except HQHistoryError as e:
                    raise HQHistoryError(
                        f"chunked fetch failed at chunk {i}/{len(chunks)} ({cs}~{ce}): {e}"
                    ) from e
                if bars_i:
                    try:
                        await _upsert(bars_i)
                    except Exception as e:  # noqa: BLE001
                        log.warning("[hq_history] upsert failed (non-fatal): %s", e)
            return

        # ── chunked 关闭: 1 次全拉 (向后兼容) ──
        all_rows = await self._fetch_one_chunk(stock_code, start_date, end_date, period)
        if all_rows:
            try:
                await _upsert(all_rows)
            except Exception as e:  # noqa: BLE001
                log.warning("[hq_history] upsert failed (non-fatal): %s", e)
        return

    async def _fetch_one_chunk(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
        period: str,
    ) -> List[Dict[str, Any]]:
        """单段 broker fetch + raw 1m close 数组. 内部 helper, 不做聚合.

        Returns:
            raw 1m K 线数组 (broker 1m close, stime 14位)
        """
        await self.connect()
        assert self._channel is not None

        # ── 构造 msgpacket 格式请求 (固定 period='1m' + fields=['close']) ──
        try:
            from msgpacket import MSG_TYPE_REQUEST, MsgPacket
        except ImportError:
            raise HQHistoryError("msgpacket 模块未安装: pip install msgpacket")

        ans_queue = f"HisHqAns.{uuid.uuid4().hex[:8]}"
        pkt = MsgPacket(MSG_TYPE_REQUEST)
        pkt.set_func("his_hq")
        pkt.set_headers(6, "stock_code,start_date,end_date,ans_queue,fields,period")
        pkt.add_row()
        pkt.set_value("stock_code", stock_code)
        pkt.set_value("start_date", start_date)
        pkt.set_value("end_date", end_date)
        pkt.set_value("ans_queue", ans_queue)  # 放 body 里，不是 reply_to
        pkt.set_value("fields", ",".join(_BROKER_FIELDS))
        pkt.set_value("period", _BROKER_PERIOD)  # 永远 1m
        pkt.finalize()
        _, req_bytes = pkt.encode()

        # ── 创建 answer queue 并绑定到 exchange ──
        # 必须 durable=True (非 exclusive): broker 端 his_hq 应答服务会
        # queue_declare(target, durable=True) 后再 publish, 若应答队列是
        # durable=False/exclusive, 服务端 redeclare 会 406 失败 → 该天被跳过
        # → 客户端收 0 行超时. (quota_his_test.py 即用 durable=True 成功)
        ans_q = await self._channel.declare_queue(ans_queue, durable=True, exclusive=False, auto_delete=False)
        exchange = await self._channel.declare_exchange(
            self.settings.evtrade_his_hq_exchange_name,
            aio_pika.ExchangeType.TOPIC,
            durable=True,
        )
        await ans_q.bind(exchange, routing_key=ans_queue)
        log.info(
            "[hq_history] fetching stock=%s %s~%s period=%s fields=%s ans_queue=%s",
            stock_code, start_date, end_date, period, _BROKER_FIELDS, ans_queue,
        )

        # ── 发布请求到 broker 监听的队列 ──
        await exchange.publish(
            aio_pika.Message(body=req_bytes),
            routing_key=self.settings.evtrade_his_hq_req_queue,
        )
        expected_days = _weekdays_in(start_date, end_date)
        timeout = self.settings.evtrade_his_hq_req_timeout
        log.info(
            "[hq_history] request published to queue=%s, waiting replies "
            "(expected <= %d trading days, idle timeout %ss)",
            self.settings.evtrade_his_hq_req_queue, expected_days, timeout,
        )

        # ── 等待 reply ──
        all_rows: List[Dict[str, Any]] = []
        reply_count = 0

        try:
            async with ans_q.iterator(timeout=timeout) as it:
                async for msg in it:
                    async with msg.process():
                        raw_text = msg.body.decode("utf-8")
                        # _iter_rows 产出 (columns, row) 元组, 这里只取 row dict
                        # (回测引擎需要 List[Dict], 直接存元组会缺 'open' 等列)
                        day_rows = [row for _, row in _iter_rows(raw_text)]
                        all_rows.extend(day_rows)
                    reply_count += 1
                    log.info(
                        "[hq_history] reply #%d/%d parsed into %d rows "
                        "(cumulative=%d)", reply_count, expected_days, len(day_rows),
                        len(all_rows),
                    )
                    if reply_count >= expected_days:
                        log.info(
                            "[hq_history] all expected %d trading days received, "
                            "stopping early", expected_days,
                        )
                        break
        except asyncio.TimeoutError:
            # 空闲超时 ≠ 失败: 服务端按天推送, 收完最后一天后没有结束标记,
            # 只能等 idle 超时判定"流已结束". 已收到数据就视为成功返回,
            # 只有一条都没收到才算失败 (broker 未响应).
            if not all_rows:
                log.error(
                    "[hq_history] no reply within %ss — broker his_hq 未响应",
                    timeout,
                )
                raise HQHistoryError(
                    f"his_hq reply timeout ({timeout}s), received 0 rows"
                )
            if reply_count < expected_days:
                log.warning(
                    "[hq_history] stream idle, got %d/%d day replies (%d rows) — "
                    "some days may be holidays/missing data",
                    reply_count, expected_days, len(all_rows),
                )
        finally:
            # 本轮唯一应答队列: 用完即删 (durable 队列不删会残留)
            try:
                await ans_q.delete()
            except Exception:
                pass

        log.info("[hq_history] fetched %d raw 1m bars for %s %s~%s (broker period=%s)",
                 len(all_rows), stock_code, start_date, end_date, _BROKER_PERIOD)
        return all_rows

    def _aggregate(self, all_rows: List[Dict[str, Any]], period: str) -> List[Dict[str, Any]]:
        """[已废弃] 按 period Python 聚合 — 保留供 broker 兜底/单测, 回测主路径改走 SQL.

        change 2026-09-04: fetch_bars 主路径统一用 query_bars_aggregated (SQL 聚合).
        """
        if period == "1m":
            out = all_rows
        else:
            out = aggregate_bars(all_rows, period)

        log.info("[hq_history] aggregated %d 1m bars → %d %s bars",
                 len(all_rows), len(out), period)
        return out


# ─────────────── change 2026-08-30-his-hq-chunked-fetch ───────────────


def _chunk_fully_cached(cached_bars: List[Dict[str, Any]], chunk_start: str, chunk_end: str) -> bool:
    """判断 cached_bars 是否完整覆盖 [chunk_start, chunk_end] 区间 (按日).

    Args:
        cached_bars: 已缓存 bars (stime 14位 YYYYMMDDHHMMSS)
        chunk_start / chunk_end: YYYYMMDD

    Returns:
        True = 区间内所有交易日都已缓存; False = 有缺.
    """
    if not cached_bars:
        return False
    import datetime as _dt
    covered = {b["stime"][:8] for b in cached_bars if b.get("stime")}
    s = _dt.datetime.strptime(chunk_start, "%Y%m%d").date()
    e = _dt.datetime.strptime(chunk_end, "%Y%m%d").date()
    cur = s
    while cur <= e:
        # 跳过周末 (broker 1m 数据自动跳过)
        if cur.weekday() < 5:
            date_str = cur.strftime("%Y%m%d")
            if date_str not in covered:
                return False
        cur += _dt.timedelta(days=1)
    return True


def _iter_chunks(
    start_date: str, end_date: str, chunk_days: int,
) -> List[Tuple[str, str]]:
    """把 [start_date, end_date] 拆成 N 段 (每段 ≤ chunk_days 天).

    Args:
        start_date / end_date: YYYYMMDD
        chunk_days: 段大小 (1-30)

    Returns:
        [(chunk_start_1, chunk_end_1), (chunk_start_2, chunk_end_2), ...]
        - chunk_start_i = start + (i-1) * chunk_days
        - chunk_end_i = min(start + i * chunk_days - 1, end)
        - 末段可能 < chunk_days
        - 单日区间 (start==end) → 1 段
        - 跨年正常处理 (datetime 会自动 rollover)

    Examples:
        _iter_chunks("20250101", "20250130", 10) → [
          ("20250101", "20250110"),
          ("20250111", "20250120"),
          ("20250121", "20250130"),
        ]
        _iter_chunks("20250101", "20250131", 10) → 4 段 (末段 1-1)
        _iter_chunks("20250101", "20250101", 10) → [("20250101", "20250101")]
        _iter_chunks("20241201", "20250131", 30) → [
          ("20241201", "20241230"),  # 30 天
          ("20241231", "20250131"),  # 32 天 (跨年)
        ]
    """
    import datetime as _dt

    s = _dt.datetime.strptime(start_date, "%Y%m%d").date()
    e = _dt.datetime.strptime(end_date, "%Y%m%d").date()
    if s > e:
        return []
    if chunk_days < 1:
        chunk_days = 1
    from datetime import timedelta
    out: List[Tuple[str, str]] = []
    cur = s
    while cur <= e:
        chunk_end = min(cur + timedelta(days=chunk_days - 1), e)
        out.append((cur.strftime("%Y%m%d"), chunk_end.strftime("%Y%m%d")))
        cur = chunk_end + timedelta(days=1)
    return out


# 单例
_client: Optional[HQHistoryClient] = None


def get_hq_history_client() -> HQHistoryClient:
    global _client
    if _client is None:
        _client = HQHistoryClient()
    return _client


async def fetch_his_bars(
    stock_code: str,
    start_date: str,
    end_date: str,
    period: str = "1d",
    fields: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """便捷函数 (单例)"""
    return await get_hq_history_client().fetch_bars(stock_code, start_date, end_date, period, fields)


async def close_hq_history() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None
