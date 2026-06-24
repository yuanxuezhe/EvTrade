"""
push_helpers.py — 4 个 push handler 共用的小工具

提供：
- _utcnow(): 统一返回 naive UTC datetime（DB 列无 tz）
- _str / _float / _int: 安全类型转换（broker 字段可能为 None / 字符串 / 缺失）
"""
from datetime import datetime, timezone
from typing import Any


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


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
