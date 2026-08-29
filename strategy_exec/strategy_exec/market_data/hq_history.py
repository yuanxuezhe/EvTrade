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

log = logging.getLogger(__name__)


# ─────────────── change 2026-08-30-his-hq-aggregate-bars ───────────────
# broker 永远 1m + fields=['close'], strategy_exec 端按用户 period 聚合
_BROKER_PERIOD = "1m"
_BROKER_FIELDS = ["close"]


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
        """拉历史 K 线, 返 list of dict [{stime, open, high, low, close, volume}, ...]

        change 2026-08-30-his-hq-aggregate-bars:
        - broker his_hq 永远收 period='1m' + fields=['close'] (broker 单源真相)
        - strategy_exec 端按用户 period 聚合 (1m / 5m / 15m / 30m / 60m / 1d)
        - 1d 聚合按 A股交易日历 (周末跳过)

        change 2026-08-30-his-hq-chunked-fetch:
        - 长区间 (≥30 天) broker 单次 fetch 30s 超时 → 拆 N 段 (默认 10 天/批)
        - 串行调 _fetch_one_chunk() → 拼凑 + sort by stime
        - 任一段 raise → 立即 raise (不返部分数据)
        """
        # ── change 2026-08-30-his-hq-chunked-fetch: chunked 调度 ──
        if self.settings.his_hq_chunk_enabled:
            chunks = _iter_chunks(start_date, end_date, self.settings.his_hq_chunk_days)
            log.info(
                "[hq_history] chunked fetch enabled: stock=%s %s~%s → %d chunks (chunk_days=%d)",
                stock_code, start_date, end_date, len(chunks), self.settings.his_hq_chunk_days,
            )
            all_bars: List[Dict[str, Any]] = []
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
                all_bars.extend(bars_i)
            # 拼凑后 sort by stime (broker 内部顺序可能乱)
            all_bars.sort(key=lambda b: b.get("stime", ""))
            return self._aggregate(all_bars, period)

        # ── chunked 关闭: 1 次全拉 (向后兼容) ──
        all_rows = await self._fetch_one_chunk(stock_code, start_date, end_date, period)
        return self._aggregate(all_rows, period)

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
        """按用户 period 聚合 (broker 永远 1m + close) — 内部 helper."""
        if period == "1m":
            # 1m 直接返 (无聚合), open/high/low 用 close 兜底 (broker 1m 不返)
            out = all_rows
        else:
            out = aggregate_bars(all_rows, period)

        log.info("[hq_history] aggregated %d 1m bars → %d %s bars",
                 len(all_rows), len(out), period)
        return out


# ─────────────── change 2026-08-30-his-hq-chunked-fetch ───────────────


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
