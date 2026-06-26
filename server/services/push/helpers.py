"""
push_helpers.py — 4 个 push handler 共用的小工具

提供：
- _str / _float / _int: 安全类型转换（broker 字段可能为 None / 字符串 / 缺失）

v10 时间戳工具已从 services/push_helpers.py 移至 server/utils/time.py。
此处保留兼容垫片，re-export 所有符号。
"""
from typing import Any, Optional

# 时间工具（权威位置在 server/utils/time.py）
from server.utils.time import (
    _utcnow,
    TS_FMT,
    format_ts,
    parse_broker_ts,
    format_db_dt,
)


def _str(v: Any, default: str = '') -> str:
    """安全取字符串值"""
    if v is None:
        return default
    return str(v)


def _float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default
