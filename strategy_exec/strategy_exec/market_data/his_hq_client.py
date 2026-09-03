"""
strategy_exec.market_data.his_hq_client — 跨服务共享的 broker his_hq 客户端

📌 用途:
- server/services/quote_sync (历史行情补全 API)
- scripts/fetch_minute_bars.py (CLI 拉历史行情)
- strategy_exec.market_data.hq_history (回测缓存 + chunked)

📌 设计:
- 单连接 + 单 channel (aio_pika, async)
- msgpacket 协议 + durable 应答队列 + idle 超时空日跳过
- fields 参数化 (默认 6 字段 OHLCV+amount)
- to_record() 统一兜底语义:
    - VWAP = amount/(volume*100) 元/股 (A股 volume 单位是手)
    - broker 端 xtquant 实盘只返 close (其他 0 占位), 单 1m bar 内
      open/high/low = close (无 H/L 区分意义), 用 close 兜底
- END_OF_HIS_HQ_MARKER 兼容 (broker change B): 收到即 break → 无数据日秒回

⚠️ 跟旧 server/services/quote_sync/broker.py 的差异:
- 旧 server broker 写死 VWAP 公式 + 不做 close 兜底 OHL
- 旧 scripts/fetch_minute_bars.py 用 amount/volume (元/手, 错的)
- 公共 client 统一为 VWAP=amount/(volume*100) + close 兜底 OHL

⚠️ 跟 strategy_exec.market_data.hq_history.py 的差异:
- hq_history 里 HQHistoryClient.fetch_bars 是 strategy_exec 独有:
    - chunked 调度 (10天/批) + cache (minute_bars FULL HIT skip broker)
    - _BROKER_FIELDS = ["close"] (只拉 close, 用 aggregator 兜底 OHL)
- his_hq_client 是通用版:
    - 不做 chunked (调用方自己 chunk)
    - DEFAULT_FIELDS = OHLCV+amount (server/scripts 需要多字段)
"""
from __future__ import annotations

import asyncio
import datetime
import logging
import uuid
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Tuple

import aio_pika
from aio_pika.abc import AbstractRobustChannel, AbstractRobustConnection

log = logging.getLogger(__name__)


# ───────────────────────── 常量 ─────────────────────────

# broker 请求字段 (xtquant get_market_data_ex 支持的字段)
DEFAULT_FIELDS = ["open", "high", "low", "close", "volume", "amount"]

# 协议周期 (固定 1m; 聚合 OHLCV 由 strategy_exec aggregator 在上层做)
DEFAULT_PERIOD = "1m"

# broker 结束标记 (broker change B): 每天循环结束后发, 让无数据日 (周末/假日)
# 秒级返回 (实测 ~0.9s), 不必等 idle timeout。旧 broker 无此标记 →
# 客户端回退到 idle 超时 (兼容)。
# 与 iquant/quota_his.py:END_OF_HIS_HQ_MARKER 保持一致 (必须同步)。
END_OF_HIS_HQ_MARKER = "#END_OF_HIS_HQ#"


# ───────────────────────── 纯函数 ─────────────────────────

def _to_float(v: Any) -> Optional[float]:
    """str/float/int/None → float|None. 失败/空 返 None (调用方决定兜底).

    跟原 broker.py `_to_float` 一致 — 保留 None 返回, 让调用方 f() 统一兜底 0.0,
    而不是把所有失败路径都吞成 0 (便于测试断言 None 与 0 区分).
    """
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _iter_rows(raw_text: str) -> Iterator[Tuple[List[str], Dict[str, str]]]:
    """Parse broker reply body.

    Wire format:
        <col_header>\\n<row1>|<row2>|...
    where row_i = "<stime>#<field1>#<field2>..."

    产出 (columns, row_dict) 元组. columns 是 broker 端 col_header 切分后的列表,
    row_dict 是 zip(columns, values) 后的 dict.
    """
    header_line, _, body = raw_text.partition("\n")
    if not body.strip():
        return
    columns = header_line.split(",")
    for line in body.split("|"):
        if not line:
            continue
        values = line.split("#")
        yield columns, dict(zip(columns, values))


def _weekdays_in(start: str, end: str) -> int:
    """YYYYMMDD 区间内工作日数 = broker 按天推送的 reply 条数上界.

    节假日/无数据天 broker 跳过 → 实际 reply 数 <= 工作日数.
    用于「收满即停」的早停判定, 也用于空日判定 (expected>=1 但 0 行=空日).
    """
    try:
        s = datetime.datetime.strptime(start[:8], "%Y%m%d").date()
        e = datetime.datetime.strptime(end[:8], "%Y%m%d").date()
    except ValueError as ex:
        raise ValueError(f"bad date format: start={start!r} end={end!r}: {ex}") from ex
    if s > e:
        return 0
    return sum(
        1
        for i in range((e - s).days + 1)
        if (s + datetime.timedelta(days=i)).weekday() < 5
    )


def to_record(
    stock_code: str,
    b: Dict[str, str],
    *,
    fields: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """broker 1m dict → minute_bars 行.

    统一语义 (跨 server/scripts/strategy_exec 一致):
    - VWAP = amount/(volume*100) 元/股 (A股 volume 单位是手, 1 手=100 股)
    - broker 端 xtquant `get_market_data_ex` 实盘只返 close (2026-08-30 实测确认),
      其他字段返 0 占位. 兜底策略:
        * open/high/low = 0 → 用 close 兜底 (单 1m bar 内 H=L=O=C, 没意义区分)
        * 用 `if raw == 0` 而非 `raw or close`, 避免 close=0 的极端行情被误判
    - volume=0 → avg_price=0.0 (broker stub 不带 amount/volume)

    Args:
        stock_code: 证券代码
        b: broker 1m dict (含 stime + fields 字段)
        fields: 请求字段列表 (默认 DEFAULT_FIELDS). 用于兼容 strategy_exec
            只拉 close 的场景.

    Returns:
        minute_bars 表行 dict (含 stock_code, stime, open, close, high, low,
        avg_price, volume)
    """
    if fields is None:
        fields = DEFAULT_FIELDS

    def f(k: str) -> float:
        v = _to_float(b.get(k))
        return 0.0 if v is None else v

    close = f("close")
    # broker 端 fields=open,high,low,close,volume,amount → 实盘只 close 有值,
    # 其他若为 0 (broker stub 兜底空) → 用 close 兜底.
    # 用 `if x == 0` 而非 `x or close` 避免误判 close=0 的极端行情.
    raw_open = f("open");   open_v = close if raw_open == 0 else raw_open
    raw_high = f("high");   high_v = close if raw_high == 0 else raw_high
    raw_low  = f("low");    low_v  = close if raw_low  == 0 else raw_low
    vol = int(f("volume"))
    amt = f("amount")
    return {
        "stock_code": stock_code,
        "stime": str(b.get("stime", "")),
        "open": open_v,
        "close": close,
        "high": high_v,
        "low": low_v,
        "avg_price": (amt / (vol * 100)) if vol > 0 else 0.0,
        "volume": vol,
    }


# ───────────────────────── Client ─────────────────────────

class HisHqClient:
    """跨服务共享的 broker his_hq 客户端.

    设计:
    - 单连接 + 单 channel (aio_pika)
    - async fetch (调用方需 await)
    - 不带 chunked/cache (调用方自己决定 — strategy_exec 走 hq_history,
      server/scripts 走自己的分块逻辑)
    - 跟 iquant/quota_his.py 的 END_OF_HIS_HQ_MARKER 兼容
    - 默认 fields=OHLCV+amount (server/scripts 需要多字段, strategy_exec
      调 fetch_bars 时改用 ["close"])

    Examples:
        client = HisHqClient()
        await client.connect()
        bars = await client.fetch_bars("159992.SZ", "20260825", "20260825")
        for bar in bars:
            rec = to_record("159992.SZ", bar)
            await client.close()
    """

    def __init__(
        self,
        rabbitmq_url: Optional[str] = None,
        exchange_name: Optional[str] = None,
        req_queue: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> None:
        """初始化. 不传参数从 settings 读 (兼容 strategy_exec 配置); 显式传则覆盖.

        Args:
            rabbitmq_url: 完整 AMQP URL. 不传读 settings.evtrade_rabbitmq_url.
            exchange_name: broker exchange 名. 不传读 settings.
            req_queue: 请求队列名. 不传读 settings.
            timeout: idle 超时秒数. 不传读 settings.
        """
        self._connection: Optional[AbstractRobustConnection] = None
        self._channel: Optional[AbstractRobustChannel] = None
        self._overrides = {
            "rabbitmq_url": rabbitmq_url,
            "exchange_name": exchange_name,
            "req_queue": req_queue,
            "timeout": timeout,
        }

    # ------- settings 懒加载 (兼容 strategy_exec 的 pydantic settings) -------

    @property
    def settings(self) -> Any:
        """懒加载 settings (strategy_exec 用 pydantic-settings; server 用普通 BaseSettings).

        子类可 override 此 property 注入自己的 settings provider. 默认 strategy_exec 风格.
        """
        from strategy_exec.config import get_settings
        return get_settings()

    def _resolve(self, key: str) -> Any:
        """先看 override, 再看 settings."""
        v = self._overrides.get(key)
        if v is not None:
            return v
        s = self.settings
        if key == "rabbitmq_url":
            return getattr(s, "evtrade_rabbitmq_url", None)
        if key == "exchange_name":
            return getattr(s, "evtrade_his_hq_exchange_name", None)
        if key == "req_queue":
            return getattr(s, "evtrade_his_hq_req_queue", None)
        if key == "timeout":
            return getattr(s, "evtrade_his_hq_req_timeout", 30)
        return None

    # ------- 连接管理 -------

    async def connect(self) -> None:
        if self._connection is not None and not self._connection.is_closed:
            return
        url = self._resolve("rabbitmq_url")
        if not url:
            raise RuntimeError(
                "rabbitmq_url 未配置 (settings.evtrade_rabbitmq_url 缺失或显式 override 为空)"
            )
        self._connection = await aio_pika.connect_robust(url)
        self._channel = await self._connection.channel()
        log.info("[his_hq_client] connected to %s", url)

    async def close(self) -> None:
        if self._connection is not None and not self._connection.is_closed:
            await self._connection.close()
        self._connection = None
        self._channel = None

    # ------- fetch 单段 -------

    async def fetch_bars(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
        *,
        fields: Optional[List[str]] = None,
        period: str = DEFAULT_PERIOD,
    ) -> List[Dict[str, Any]]:
        """单段 fetch (cs~ce 同一天/几天都可). 返 List[dict].

        Wire format 同 broker 端 iquant/quota_his.py:
            col_header = "stime," + ",".join(fields)
            payload = "{stime}#f1#f2...#fN" + "|" + ... ("|" 分隔每根)
            body = col_header + "\n" + "|".join(rows)

        Returns:
            - 交易日 → N 根 (broker 1m close)
            - 周末/假日/无数据 (broker 0 行, idle 超时 / END marker) → []
              调用方视为「成功空」
        Raises:
            ConnectionError: 消息发布/订阅失败 (broker 不可达/msgpacket 缺失等)
        """
        if self._channel is None:
            await self.connect()
        ch = self._channel
        if fields is None:
            fields = DEFAULT_FIELDS

        try:
            from msgpacket import MSG_TYPE_REQUEST, MsgPacket
        except ImportError as ex:
            raise ConnectionError("msgpacket 模块未安装: pip install msgpacket") from ex

        ans = f"HisHq.{uuid.uuid4().hex[:8]}"
        pkt = MsgPacket(MSG_TYPE_REQUEST)
        pkt.set_func("his_hq")
        pkt.set_headers(6, "stock_code,start_date,end_date,ans_queue,fields,period")
        pkt.add_row()
        # change 2026-09-03 (broker-fields-delimiter): msgpacket C 库把 ',' 当作字段值
        # 终止符 (libmsgpacket.so 内置 CSV 风格 delimiter), 所以 fields 串必须
        # 用竖线 '|' 分隔 (broker 端 iquant/quota_his.py 同步改 fields_str.split("|")).
        # 实测: set_value_str("fields", "open,high,...") → broker decode 仅 'open'.
        for k, v in [
            ("stock_code", stock_code),
            ("start_date", start_date),
            ("end_date", end_date),
            ("ans_queue", ans),
            ("fields", "|".join(fields)),
            ("period", period),
        ]:
            pkt.set_value(k, v)
        pkt.finalize()
        _, req = pkt.encode()

        # 应答队列 durable=True (broker 端 redeclare durable, exclusive 会 406 跳过)
        q = await ch.declare_queue(ans, durable=True, exclusive=False, auto_delete=False)
        ex_name = self._resolve("exchange_name") or "quota_his.exchange"
        ex = await ch.declare_exchange(
            ex_name, aio_pika.ExchangeType.TOPIC, durable=True,
        )
        req_queue = self._resolve("req_queue") or "EvTrade.ReqHisHq"
        await q.bind(ex, routing_key=ans)
        await ex.publish(aio_pika.Message(body=req), routing_key=req_queue)

        expected = _weekdays_in(start_date, end_date)
        timeout = self._resolve("timeout") or 30
        rows: List[Dict[str, Any]] = []
        try:
            async with q.iterator(timeout=timeout) as it:
                async for msg in it:
                    async with msg.process():
                        txt = msg.body.decode("utf-8")
                        # 结束标记 (broker change B): 收到即 break, 无数据日秒返
                        if END_OF_HIS_HQ_MARKER in txt:
                            break
                        rows.extend(row for _, row in _iter_rows(txt))
                    # 收满工作日条数 → 早停 (broker 推送 1 条/工作日, 240 根/日)
                    if expected and len(rows) >= expected * 240:
                        break
        except asyncio.TimeoutError:
            # idle 超时: 流结束 (旧 broker 无 END marker 的回退). 已有 rows 正常, 空 chunk 返 [].
            pass
        finally:
            try:
                await q.delete()
            except Exception:
                log.exception("[his_hq_client] delete ans_queue %s failed", ans)
        return rows


# ───────────────────────── 单例 helpers ─────────────────────────

_client: Optional[HisHqClient] = None


def get_client() -> HisHqClient:
    """返单例 (lazy init). 调用方负责 await connect() 和 close()."""
    global _client
    if _client is None:
        _client = HisHqClient()
    return _client


async def close_client() -> None:
    """应用关闭时调用."""
    global _client
    if _client is not None:
        await _client.close()
        _client = None


__all__ = [
    "DEFAULT_FIELDS",
    "DEFAULT_PERIOD",
    "END_OF_HIS_HQ_MARKER",
    "HisHqClient",
    "to_record",
    "_iter_rows",
    "_weekdays_in",
    "_to_float",
    "get_client",
    "close_client",
]