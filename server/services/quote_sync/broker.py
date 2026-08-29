"""
server/services/quote_sync/broker.py — 自包含 his_hq 单日多字段 broker 客户端

拉单只证券「某一天」的 1m K 线 (open/high/low/close/volume/amount), 算均价
VWAP = amount/(volume*100) (元/股; A股 volume 单位是手, 1 手=100 股),
供前端驱动按日补全 / 启动自动增量同步调用。

server 进程自包含 (不 import strategy_exec):
  - broker 协议 (msgpacket + durable 应答队列 + idle 超时空日跳过) 与
    strategy_exec.market_data.hq_history 行为一致, 但 fields 参数化
    (strategy_exec 写死 close, 这里要 OHLCV+amount)
  - 配置读 server.config.settings 的 HIS_HQ_* (与 strategy_exec/.env 解耦)

协议要点 (来自 quota_his / hq_history 实战):
  - exchange quota_his.exchange (TOPIC, durable), 请求队列 EvTrade.ReqHisHq
  - ans_queue 放 body 字段里 (不是 reply_to), 用 durable=True 应答队列
    (broker 端 redeclare durable, exclusive 会 406 跳过该天)
  - broker 按天推送 reply, 无结束标记 → idle 超时判定流结束; 收满
    _weekdays_in(cs,ce) 条提前停
"""
from __future__ import annotations

import asyncio
import datetime
import logging
import uuid
from typing import Any, Dict, List, Optional

import aio_pika

from server.config import settings

log = logging.getLogger(__name__)

# broker 请求字段 (xtquant get_market_data_ex 支持 OHLCV+amount)
BROKER_FIELDS = ["open", "high", "low", "close", "volume", "amount"]
_BROKER_PERIOD = "1m"


class BrokerError(Exception):
    """拉 broker 历史行情失败 (区分于「空日」— 空日不 raise)"""


def _iter_rows(raw_text: str):
    """Parse broker reply body → 每行 dict.

    Wire format: `<col_header>\\n<row1>|<row2>|...`, row_i = `<stime>#<f1>#<f2>...`
    产出 (columns, row_dict) 元组; 调用方取 row_dict。
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
    """YYYYMMDD 区间内工作日数 = broker 按天推送的 reply 条数上界。

    节假日/无数据天被 broker 跳过 → 实际 reply 数 <= 工作日数。
    用于「收满即停」的早停判定, 也用于空日判定 (expected>=1 但 0 行=空日)。
    """
    s = datetime.datetime.strptime(start[:8], "%Y%m%d").date()
    e = datetime.datetime.strptime(end[:8], "%Y%m%d").date()
    if s > e:
        return 0
    return sum(
        1
        for i in range((e - s).days + 1)
        if (s + datetime.timedelta(days=i)).weekday() < 5
    )


def to_record(stock_code: str, b: Dict[str, Any]) -> Dict[str, Any]:
    """broker 1m dict → minute_bars 行.

    均价 VWAP = amount/(volume*100) (元/股; volume 单位手)。volume=0 → 0.0。
    """
    def f(k: str) -> float:
        try:
            return float(b.get(k, 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    vol = int(f("volume"))
    amt = f("amount")
    return {
        "stock_code": stock_code,
        "stime": str(b.get("stime", "")),
        "open": f("open"),
        "close": f("close"),
        "high": f("high"),
        "low": f("low"),
        "avg_price": (amt / (vol * 100)) if vol > 0 else 0.0,
        "volume": vol,
    }


class HisHqClient:
    """async broker his_hq 客户端 (单连接, 复用 channel)。server 自包含。"""

    def __init__(self) -> None:
        self._connection: Optional[aio_pika.abc.AbstractRobustConnection] = None
        self._channel = None

    async def connect(self) -> None:
        if self._connection is not None and not self._connection.is_closed:
            return
        self._connection = await aio_pika.connect_robust(settings.HIS_HQ_RABBITMQ_URL)
        self._channel = await self._connection.channel()
        log.info("[quote_sync.broker] connected to %s", settings.HIS_HQ_RABBITMQ_URL)

    async def close(self) -> None:
        if self._connection is not None and not self._connection.is_closed:
            await self._connection.close()
        self._connection = None
        self._channel = None

    async def fetch_one_day(
        self, stock_code: str, day: str, fields: List[str] = BROKER_FIELDS,
    ) -> List[Dict[str, Any]]:
        """拉单只证券「某一天」(day=YYYYMMDD) 的 1m 多字段 K 线。

        Returns:
            List[dict{stime,open,high,low,close,volume,amount}] (broker 原样, 未算均价)
            - 交易日 → 240 根左右
            - 假日/周末/无数据 (broker 0 行, idle 超时) → [] (调用方视为「成功空」, 游标照常推进)

        Raises:
            BrokerError: 连接/发布级失败 (broker 不可达、msgpacket 缺失等)。
                注: 单日「收不到任何 reply」无法与市场假日区分, 按需求归入 [] (成功空)。
        """
        cs = ce = day
        if self._channel is None:
            await self.connect()
        ch = self._channel
        try:
            from msgpacket import MSG_TYPE_REQUEST, MsgPacket
        except ImportError:
            raise BrokerError("msgpacket 模块未安装: pip install msgpacket")

        ans = f"QuoteSync.{uuid.uuid4().hex[:8]}"
        pkt = MsgPacket(MSG_TYPE_REQUEST)
        pkt.set_func("his_hq")
        pkt.set_headers(6, "stock_code,start_date,end_date,ans_queue,fields,period")
        pkt.add_row()
        for k, v in [
            ("stock_code", stock_code), ("start_date", cs), ("end_date", ce),
            ("ans_queue", ans), ("fields", ",".join(fields)), ("period", _BROKER_PERIOD),
        ]:
            pkt.set_value(k, v)
        pkt.finalize()
        _, req = pkt.encode()

        # 应答队列 durable=True (broker 端 redeclare durable, exclusive 会 406 跳过)
        q = await ch.declare_queue(ans, durable=True, exclusive=False, auto_delete=False)
        ex = await ch.declare_exchange(
            settings.HIS_HQ_EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True,
        )
        await q.bind(ex, routing_key=ans)
        await ex.publish(aio_pika.Message(body=req), routing_key=settings.HIS_HQ_REQ_QUEUE)

        expected = _weekdays_in(cs, ce)  # 单日: 工作日=1 / 周末假日=0
        timeout = settings.HIS_HQ_TIMEOUT
        rows: List[Dict[str, Any]] = []
        try:
            async with q.iterator(timeout=timeout) as it:
                async for msg in it:
                    async with msg.process():
                        txt = msg.body.decode("utf-8")
                        rows.extend(row for _, row in _iter_rows(txt))
                    if expected and len(rows) >= expected * 240:
                        break
        except asyncio.TimeoutError:
            # idle 超时 = 流结束, 直接返已收 rows。
            #   交易日有数据 → rows 非空
            #   假日/无数据 → rows 空 (broker 不推送, idle 超时) → 返 [] = 「成功空」
            # broker 日历工作日 (_weekdays_in) 分不清「市场假日」vs「broker 挂」,
            # 两者都是日历工作日且 0 行 → 按需求 (假日=成功空, 游标照常推进) 一律返 []。
            # 真正可区分的 broker 故障是连接级失败 (connect/publish 抛错), 那会自然上抛。
            pass
        finally:
            try:
                await q.delete()
            except Exception:
                log.exception("[quote_sync.broker] delete ans_queue %s failed", ans)
        return rows


# ─────────────── 模块级单例 (启动自动同步 / API 共用) ───────────────

_client: Optional[HisHqClient] = None


def get_his_hq_client() -> HisHqClient:
    global _client
    if _client is None:
        _client = HisHqClient()
    return _client


async def close_his_hq_client() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None
