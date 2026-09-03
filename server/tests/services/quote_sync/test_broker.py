"""
server/tests/services/quote_sync/test_broker.py — his-quote-backfill P2 单测

纯函数 (无 IO, 安全):
  - to_record VWAP 公式 (amount/(volume*100), volume=0 兜底)
  - _weekdays_in 边界 (单日工作日/周末/跨年/start>end)
  - _iter_rows wire 格式解析
  - sync._cap_day 昨天封顶 / _next_day
不碰生产数据 (minute_bars/quote_sync_config 不写)。
"""
from datetime import datetime

import pytest

from server.services.quote_sync.broker import (
    to_record, _weekdays_in, _iter_rows,
)
from server.services.quote_sync.sync import _cap_day, _next_day


# ─────────────── to_record / VWAP ───────────────


def test_to_record_vwap_normal():
    """VWAP = amount/(volume*100); volume 单位手, 1 手=100 股."""
    r = to_record("159992.SZ", {
        "stime": "20260825093100", "open": "0.844", "high": "0.847",
        "low": "0.843", "close": "0.843", "volume": "296106", "amount": "25011372.0",
    })
    # 25011372 / (296106*100) = 0.84468...
    assert r["stock_code"] == "159992.SZ"
    assert r["stime"] == "20260825093100"
    assert r["open"] == 0.844 and r["close"] == 0.843
    assert r["high"] == 0.847 and r["low"] == 0.843
    assert r["volume"] == 296106
    assert 0.84 < r["avg_price"] < 0.85  # 元/股, 与 close 同量级
    assert abs(r["avg_price"] - 25011372.0 / (296106 * 100)) < 1e-9


def test_to_record_vwap_zero_volume():
    """volume=0 → avg_price=0.0 (不除零)."""
    r = to_record("159992.SZ", {
        "stime": "20260825093100", "open": "0", "high": "0",
        "low": "0", "close": "0.843", "volume": "0", "amount": "0",
    })
    assert r["volume"] == 0
    assert r["avg_price"] == 0.0
    assert r["close"] == 0.843


def test_to_record_bad_values_fallback_zero():
    """字段缺失/非数字 → 0.0 兜底, 不抛."""
    r = to_record("X", {"stime": "20260101093100"})
    assert r["open"] == 0.0 and r["close"] == 0.0 and r["avg_price"] == 0.0
    assert r["volume"] == 0


# ─────────────── _weekdays_in ───────────────


def test_weekdays_single_trading_day():
    assert _weekdays_in("20260825", "20260825") == 1  # 周二


def test_weekdays_single_weekend():
    assert _weekdays_in("20260829", "20260829") == 0  # 周六
    assert _weekdays_in("20260830", "20260830") == 0  # 周日


def test_weekdays_multi_day_range():
    # 20260824(一)~20260828(五) = 5 个工作日
    assert _weekdays_in("20260824", "20260828") == 5


def test_weekdays_start_after_end():
    assert _weekdays_in("20260901", "20260825") == 0


def test_weekdays_cross_month():
    # 20260831(一)~20260904(五) 全工作日 = 5
    assert _weekdays_in("20260831", "20260904") == 5


# ─────────────── _iter_rows ───────────────


def test_iter_rows_parses_wire_format():
    """header\\nrow1|row2, row = stime#f1#f2..."""
    raw = "stime,open,close\n20260825093100#0.844#0.843|20260825093200#0.845#0.842"
    rows = list(_iter_rows(raw))
    assert len(rows) == 2
    cols, row0 = rows[0]
    assert cols == ["stime", "open", "close"]
    assert row0 == {"stime": "20260825093100", "open": "0.844", "close": "0.843"}
    _, row1 = rows[1]
    assert row1["stime"] == "20260825093200"


def test_iter_rows_empty_body():
    assert list(_iter_rows("stime,close\n")) == []
    assert list(_iter_rows("")) == []


# ─────────────── sync 纯函数 ───────────────


def test_next_day():
    assert _next_day("20260825") == "20260826"
    assert _next_day("20260831") == "20260901"  # 跨月
    assert _next_day("20261231") == "20270101"  # 跨年


def test_cap_day_open_range_capped_yesterday():
    """end_date 空 → 封顶昨天 (今天不进)."""
    from server.services.quote_sync.sync import _yesterday
    assert _cap_day("") == _yesterday()


def test_cap_day_end_after_yesterday_capped():
    """end_date 比昨天还远 → 仍封顶昨天."""
    from server.services.quote_sync.sync import _yesterday
    assert _cap_day("20991231") == _yesterday()


def test_cap_day_end_before_yesterday_kept():
    """end_date 早于昨天 → 用 end_date."""
    assert _cap_day("20260101") == "20260101"


# ─────────────── msgpacket fields 分隔符 (broker-fields-delimiter) ───────────────


def test_msgpacket_fields_comma_truncated_to_first_field():
    """msgpacket C 库把 ',' 当作字段值终止符 — 客户端绝不能用 ',' 拼 fields.

    实测: set_value_str("fields", "open,high,low,close,volume,amount") (35 字节)
    → decode 后只 'open' (4 字节, 截到第一个 ',' 前). 这是 broker 只返 open 的根因.
    """
    pytest.importorskip("msgpacket")
    from msgpacket import MSG_TYPE_REQUEST, MsgPacket
    pkt = MsgPacket(MSG_TYPE_REQUEST)
    pkt.set_func("his_hq")
    pkt.set_headers(6, "stock_code,start_date,end_date,ans_queue,fields,period")
    pkt.add_row()
    pkt.set_value("fields", "open,high,low,close,volume,amount")
    pkt.finalize()
    _, req = pkt.encode()
    pkt2 = MsgPacket.decode(req)
    v = pkt2.get_value_str("fields")
    # 证明 ',' delimiter 会把 fields 截到 'open'
    assert v == "open"
    assert "," in v or len(v) == 4  # broker 实际收到的字段数 = 1


def test_msgpacket_fields_pipe_keeps_full_string():
    """改用 '|' 分隔后, broker 收到完整 6 字段 (跟客户端 fetch_bars 一致).

    HisHqClient.fetch_bars 用 '|'.join(DEFAULT_FIELDS) 拼 fields (见 his_hq_client.py fetch_bars 注释).
    """
    pytest.importorskip("msgpacket")
    from msgpacket import MSG_TYPE_REQUEST, MsgPacket
    pkt = MsgPacket(MSG_TYPE_REQUEST)
    pkt.set_func("his_hq")
    pkt.set_headers(6, "stock_code,start_date,end_date,ans_queue,fields,period")
    pkt.add_row()
    pkt.set_value("fields", "open|high|low|close|volume|amount")
    pkt.finalize()
    _, req = pkt.encode()
    pkt2 = MsgPacket.decode(req)
    v = pkt2.get_value_str("fields")
    assert v == "open|high|low|close|volume|amount"
    # broker 端 split("|") 应分出 6 个字段
    fields_list = [f.strip() for f in v.split("|") if f.strip()]
    assert fields_list == ["open", "high", "low", "close", "volume", "amount"]
