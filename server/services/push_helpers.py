"""
push_helpers.py — 4 个 push handler 共用的小工具

提供：
- _utcnow(): 统一返回 naive UTC datetime（DB 列无 tz）
- _str / _float / _int: 安全类型转换（broker 字段可能为 None / 字符串 / 缺失）

v10 时间戳工具（rpc-field-alignment-ts-unify commit 3）：
- format_ts(): 统一时间戳字符串化入口，输出 "YYYY-MM-DD HH:MM:SS.fff"
- parse_broker_ts(): 把 broker 各种格式（"HH:MM:SS" / "HHMMSS" / "YYYYMMDDHHMMSS" / 毫秒紧凑串）解析为标准格式
- format_db_dt(): 把 DB DateTime（naive UTC）序列化为标准格式字符串
"""
from datetime import datetime, timezone
from typing import Any, Optional


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


# ================================================================
# v10 时间戳工具
# ================================================================

# 标准时间戳格式: "YYYY-MM-DD HH:MM:SS.fff" (23 字符)
TS_FMT = "%Y-%m-%d %H:%M:%S.%f"


def format_ts(dt: Optional[datetime] = None, *, tz: str = 'local') -> str:
    """统一时间戳字符串化入口（v10）

    Args:
        dt: datetime 对象;None 表示用当前时间
        tz: 'local' (本地时间) / 'utc' (UTC);业务时间戳用 local,系统时间戳用 utc

    Returns:
        "2026-06-24 17:56:28.281" (23 字符)

    Example:
        >>> format_ts()
        '2026-06-25 09:30:00.123'
        >>> format_ts(datetime(2026, 6, 24, 17, 56, 28, 281000), tz='local')
        '2026-06-24 17:56:28.281'
    """
    if dt is None:
        dt = datetime.now()
    return dt.strftime(TS_FMT)[:-3]  # %f 是 6 位微秒, 取前 3 位 = 毫秒


def parse_broker_ts(s: str, trd_date: str = '', *, tz: str = 'local') -> str:
    """把 broker 推送的多种时间格式解析为标准格式（v10）

    支持输入格式（按优先级尝试）:
      1. "HH:MM:SS"          → 需传 trd_date 补全日期
      2. "HH:MM:SS.fff"      → 需传 trd_date 补全日期
      3. "HHMMSS"            → 需传 trd_date 补全日期
      4. "YYYYMMDDHHMMSS"    → 14 位紧凑串
      5. "YYYYMMDDHHMMSSfff" → 17 位紧凑串
      6. "2026-06-24 17:56:28" / "2026-06-24 17:56:28.281" → 已标准格式直接返回

    Args:
        s: broker 推送的时间字符串
        trd_date: 8 位 YYYYMMDD;用于"HH:MM:SS"等缺日期的格式补全
        tz: 'local' / 'utc';不影响输出(仅显示本地时区值)

    Returns:
        标准格式 "2026-06-24 17:56:28.281" (23 字符);解析失败返回原串

    Example:
        >>> parse_broker_ts("09:30:00", "20260614")
        '2026-06-14 09:30:00.000'
        >>> parse_broker_ts("20260614093000")
        '2026-06-14 09:30:00.000'
    """
    if not s:
        return ""
    s = str(s).strip()
    # 已是标准格式
    if len(s) == 23 and s[10] == ' ' and s[4] == '-' and s[13] == ':':
        return s
    if len(s) == 19 and s[10] == ' ' and s[4] == '-' and s[13] == ':':
        return s + ".000"
    # 17 位紧凑串 (YYYYMMDDHHMMSSfff)
    if len(s) == 17 and s.isdigit():
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]} {s[8:10]}:{s[10:12]}:{s[12:14]}.{s[14:17]}"
    # 14 位紧凑串 (YYYYMMDDHHMMSS)
    if len(s) == 14 and s.isdigit():
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]} {s[8:10]}:{s[10:12]}:{s[12:14]}.000"
    # HH:MM:SS 或 HH:MM:SS.fff
    if ':' in s and len(s) <= 12 and (s.replace(':', '').replace('.', '').isdigit()):
        time_part = s if '.' in s else (s + ".000")
        if trd_date and len(trd_date) == 8 and trd_date.isdigit():
            date_part = f"{trd_date[0:4]}-{trd_date[4:6]}-{trd_date[6:8]}"
            return f"{date_part} {time_part}"
        # 缺 trd_date: 用 1970-01-01 占位
        return f"1970-01-01 {time_part}"
    # HHMMSS (6 位紧凑)
    if len(s) == 6 and s.isdigit():
        time_part = f"{s[0:2]}:{s[2:4]}:{s[4:6]}.000"
        if trd_date and len(trd_date) == 8 and trd_date.isdigit():
            date_part = f"{trd_date[0:4]}-{trd_date[4:6]}-{trd_date[6:8]}"
            return f"{date_part} {time_part}"
        return f"1970-01-01 {time_part}"
    # 解析失败:原样返回(不抛,保 broker 原始数据不丢)
    return s


def format_db_dt(dt: Optional[datetime], *, tz: str = 'utc') -> str:
    """把 DB DateTime (naive UTC) 序列化为标准格式字符串（v10）

    DB 内部 DateTime 列统一存 naive UTC;
    序列化到 API 响应时,按 'utc' / 'local' 转换并输出标准格式。

    Args:
        dt: datetime 对象;None 时返回空串
        tz: 'utc' / 'local'

    Returns:
        "2026-06-24 17:56:28.281" 或 ""

    Example:
        >>> format_db_dt(datetime(2026, 6, 24, 17, 56, 28, 281000))
        '2026-06-24 17:56:28.281'
    """
    if dt is None:
        return ""
    if tz == 'utc':
        # naive UTC → 加 tzinfo 后转 UTC 字符串
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        # 格式化为 UTC 字符串(本地时区值)
        return dt.strftime(TS_FMT)[:-3]
    # tz='local': datetime 视为本地时间,直接格式化
    return dt.strftime(TS_FMT)[:-3]

