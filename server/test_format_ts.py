"""
test_format_ts.py — v10 时间戳工具函数测试（rpc-field-alignment-ts-unify commit 4）

覆盖：
- format_ts(): 当前时间 / 指定时间 / 本地 vs UTC
- parse_broker_ts(): 5+ 种 broker 时间格式
- format_db_dt(): DB DateTime 序列化
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

import pytest
from datetime import datetime

from server.services.push_helpers import (
    format_ts,
    parse_broker_ts,
    format_db_dt,
    TS_FMT,
)


# ──── format_ts() ────

def test_format_ts_default_uses_current_time():
    """format_ts() 不传参 → 当前时间本地格式"""
    out = format_ts()
    # 23 字符: "YYYY-MM-DD HH:MM:SS.fff"
    assert len(out) == 23
    assert out[4] == "-"
    assert out[7] == "-"
    assert out[10] == " "
    assert out[13] == ":"
    assert out[16] == ":"
    assert out[19] == "."


def test_format_ts_with_dt():
    """format_ts(dt) → dt 转标准格式"""
    dt = datetime(2026, 6, 24, 17, 56, 28, 281000)
    out = format_ts(dt)
    assert out == "2026-06-24 17:56:28.281"


def test_format_ts_milliseconds_truncated():
    """format_ts 取毫秒(微秒前 3 位),丢后 3 位"""
    dt = datetime(2026, 6, 24, 17, 56, 28, 281999)  # 281999 微秒
    out = format_ts(dt)
    assert out == "2026-06-24 17:56:28.281"  # 281 不是 281999


def test_format_ts_local_vs_utc_documented():
    """local/utc 区别仅是文档说明,实际输出格式相同(都是 23 字符)"""
    out_local = format_ts(tz='local')
    out_utc = format_ts(tz='utc')
    assert len(out_local) == 23
    assert len(out_utc) == 23


# ──── parse_broker_ts() ────

def test_parse_broker_ts_hms_with_trd_date():
    """broker 推 "HH:MM:SS" + trd_date → 标准格式"""
    out = parse_broker_ts("09:30:00", "20260614")
    assert out == "2026-06-14 09:30:00.000"


def test_parse_broker_ts_hms_with_millis():
    """broker 推 "HH:MM:SS.fff" → 标准格式"""
    out = parse_broker_ts("09:30:00.123", "20260614")
    assert out == "2026-06-14 09:30:00.123"


def test_parse_broker_ts_hms_compact():
    """broker 推 "HHMMSS" → 标准格式"""
    out = parse_broker_ts("093000", "20260614")
    assert out == "2026-06-14 09:30:00.000"


def test_parse_broker_ts_14_digit():
    """broker 推 "YYYYMMDDHHMMSS" → 标准格式"""
    out = parse_broker_ts("20260614093000")
    assert out == "2026-06-14 09:30:00.000"


def test_parse_broker_ts_17_digit():
    """broker 推 "YYYYMMDDHHMMSSfff" → 标准格式"""
    out = parse_broker_ts("20260614093000123")
    assert out == "2026-06-14 09:30:00.123"


def test_parse_broker_ts_already_standard():
    """broker 推标准格式 → 原样返回"""
    out = parse_broker_ts("2026-06-14 09:30:00.123")
    assert out == "2026-06-14 09:30:00.123"


def test_parse_broker_ts_already_standard_no_millis():
    """broker 推标准格式但无毫秒 → 自动补 .000"""
    out = parse_broker_ts("2026-06-14 09:30:00")
    assert out == "2026-06-14 09:30:00.000"


def test_parse_broker_ts_no_trd_date_hms():
    """broker 推 "HH:MM:SS" 但无 trd_date → 1970-01-01 占位(避免 None)"""
    out = parse_broker_ts("09:30:00")
    assert out == "1970-01-01 09:30:00.000"


def test_parse_broker_ts_empty():
    """空串 → 空串"""
    assert parse_broker_ts("") == ""


def test_parse_broker_ts_unknown_format_returns_raw():
    """无法解析的格式 → 原样返回(不抛,保 broker 原始数据)"""
    out = parse_broker_ts("garbage_string_xyz")
    assert out == "garbage_string_xyz"


# ──── format_db_dt() ────

def test_format_db_dt_naive_utc():
    """naive UTC datetime → 标准格式(naive 视为 UTC)"""
    dt = datetime(2026, 6, 24, 17, 56, 28, 281000)
    out = format_db_dt(dt)
    assert out == "2026-06-24 17:56:28.281"


def test_format_db_dt_none():
    """None → 空串"""
    assert format_db_dt(None) == ""


def test_format_db_dt_aware_utc():
    """aware UTC datetime → 标准格式"""
    from datetime import timezone
    dt = datetime(2026, 6, 24, 17, 56, 28, 281000, tzinfo=timezone.utc)
    out = format_db_dt(dt)
    assert out == "2026-06-24 17:56:28.281"


# ──── TS_FMT constant ────

def test_ts_fmt_constant_format():
    """TS_FMT 是 strftime 格式,验证能用于 datetime"""
    dt = datetime(2026, 6, 24, 17, 56, 28, 281000)
    out = dt.strftime(TS_FMT)[:-3]
    assert out == "2026-06-24 17:56:28.281"
