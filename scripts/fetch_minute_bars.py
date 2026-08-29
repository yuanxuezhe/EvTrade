#!/usr/bin/env python3
"""
scripts/fetch_minute_bars.py — 拉 broker 分钟 K 线落地 minute_bars 表

从 EvTrade broker (his_hq, RabbitMQ) 拉指定标的的 1m 历史行情
(open/high/low/close/volume/amount), 算均价 avg_price = amount/volume (VWAP),
批量 upsert 进 minute_bars 表 (主键 stock_code+stime, 幂等可重跑)。

broker 协议复用 strategy_exec.market_data.hq_history (chunk 拆分 + msgpacket + reply 解析),
仅 fields 参数化 (默认 OHLCV+amount, 而非 strategy_exec 写死的 close)。

用法:
    uv run python scripts/fetch_minute_bars.py --stock 159992.SZ \
        --start 20230830 --end 20260830
    # 可选: --chunk-days 10 (默认)

落库 DB: 读 server/.env 的 EVTRADE_DB_URL (当前 = 生产 evtrade)。
空 chunk (早期年份 broker 无数据) → warning 跳过, 不 raise, 结尾报告。
"""
import argparse
import asyncio
import logging
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "strategy_exec"))

import aio_pika  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from strategy_exec.market_data.hq_history import (  # noqa: E402
    HQHistoryClient,
    _iter_chunks,
    _iter_rows,
    _weekdays_in,
)

log = logging.getLogger("fetch_minute_bars")

# broker 请求字段 (xtquant get_market_data_ex 支持)
BROKER_FIELDS = ["open", "high", "low", "close", "volume", "amount"]


async def fetch_chunk_multi(
    client: HQHistoryClient, stock: str, cs: str, ce: str,
    fields: list = BROKER_FIELDS,
) -> list:
    """单段 (cs~ce) 拉 1m 多字段 K 线, 返 List[dict{stime,open,high,low,close,volume,amount}]。

    协议同 HQHistoryClient._fetch_one_chunk, 仅 fields 参数化。
    空 chunk (broker 无数据) 返 [] (idle timeout 无行), 不 raise。
    """
    from msgpacket import MSG_TYPE_REQUEST, MsgPacket

    ch = client._channel
    settings = client.settings
    ans = f"MinuteBars.{uuid.uuid4().hex[:8]}"
    pkt = MsgPacket(MSG_TYPE_REQUEST)
    pkt.set_func("his_hq")
    pkt.set_headers(6, "stock_code,start_date,end_date,ans_queue,fields,period")
    pkt.add_row()
    for k, v in [
        ("stock_code", stock), ("start_date", cs), ("end_date", ce),
        ("ans_queue", ans), ("fields", ",".join(fields)), ("period", "1m"),
    ]:
        pkt.set_value(k, v)
    pkt.finalize()
    _, req = pkt.encode()

    # 应答队列必须 durable=True (broker 端 redeclare durable, exclusive 会 406 跳过)
    q = await ch.declare_queue(ans, durable=True, exclusive=False, auto_delete=False)
    ex = await ch.declare_exchange(
        settings.evtrade_his_hq_exchange_name, aio_pika.ExchangeType.TOPIC, durable=True,
    )
    await q.bind(ex, routing_key=ans)
    await ex.publish(aio_pika.Message(body=req), routing_key=settings.evtrade_his_hq_req_queue)

    expected = _weekdays_in(cs, ce)
    timeout = settings.evtrade_his_hq_req_timeout
    rows: list = []
    reply_count = 0
    try:
        async with q.iterator(timeout=timeout) as it:
            async for msg in it:
                async with msg.process():
                    txt = msg.body.decode("utf-8")
                    rows.extend(row for _, row in _iter_rows(txt))
                reply_count += 1
                if reply_count >= expected:
                    break
    except asyncio.TimeoutError:
        # 空闲超时: 有数据 = 成功 (流结束), 无数据 = 空 chunk (早期年份无保留)
        if not rows:
            log.warning("chunk %s~%s: no data (idle timeout, 0 rows) — 跳过", cs, ce)
    finally:
        try:
            await q.delete()
        except Exception:
            pass
    return rows


def _to_record(stock: str, b: dict) -> dict:
    """broker 1m dict → minute_bars 行 (均价 VWAP = amount/volume)。"""
    def f(k):
        return float(b.get(k, 0) or 0)
    vol = int(f("volume"))
    amt = f("amount")
    return {
        "stock_code": stock,
        "stime": b.get("stime", ""),
        "open": f("open"), "close": f("close"),
        "high": f("high"), "low": f("low"),
        "avg_price": (amt / vol) if vol > 0 else 0.0,
        "volume": vol,
    }


def upsert(engine, stock: str, bars: list) -> int:
    """批量 upsert 到 minute_bars (executemany + ON DUPLICATE KEY UPDATE, 幂等)。"""
    from sqlalchemy import text
    if not bars:
        return 0
    recs = [r for r in (_to_record(stock, b) for b in bars) if r["stime"]]
    if not recs:
        return 0
    sql = text(
        "INSERT INTO minute_bars "
        "(stock_code, stime, open, close, high, low, avg_price, volume) "
        "VALUES (:stock_code, :stime, :open, :close, :high, :low, :avg_price, :volume) "
        "ON DUPLICATE KEY UPDATE open=VALUES(open), close=VALUES(close), "
        "high=VALUES(high), low=VALUES(low), avg_price=VALUES(avg_price), volume=VALUES(volume)"
    )
    with engine.begin() as conn:
        conn.execute(sql, recs)
    return len(recs)


def run(args) -> None:
    load_dotenv(ROOT / "server" / ".env")
    from sqlalchemy import create_engine
    db_url = os.environ.get("EVTRADE_DB_URL")
    if not db_url:
        log.error("EVTRADE_DB_URL 未设置 (server/.env)")
        sys.exit(1)
    engine = create_engine(db_url, pool_pre_ping=True)

    client = HQHistoryClient()

    async def _go() -> int:
        await client.connect()
        chunks = _iter_chunks(args.start, args.end, args.chunk_days)
        log.info("stock=%s %s~%s → %d chunks (chunk_days=%d)",
                 args.stock, args.start, args.end, len(chunks), args.chunk_days)
        total = 0
        empty = 0
        for i, (cs, ce) in enumerate(chunks, 1):
            bars = await fetch_chunk_multi(client, args.stock, cs, ce)
            n = upsert(engine, args.stock, bars)
            total += n
            if n == 0:
                empty += 1
            log.info("chunk %d/%d %s~%s → %d rows (累计 %d)", i, len(chunks), cs, ce, n, total)
        await client.close()
        log.info("DONE stock=%s total=%d rows, empty_chunks=%d/%d",
                 args.stock, total, empty, len(chunks))
        return total

    try:
        asyncio.run(_go())
    finally:
        engine.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        datefmt="%H:%M:%S")
    p = argparse.ArgumentParser(description="拉 broker 分钟 K 线落地 minute_bars")
    p.add_argument("--stock", default="159992.SZ")
    p.add_argument("--start", required=True, help="YYYYMMDD")
    p.add_argument("--end", required=True, help="YYYYMMDD")
    p.add_argument("--chunk-days", type=int, default=10)
    args = p.parse_args()
    run(args)


if __name__ == "__main__":
    main()
