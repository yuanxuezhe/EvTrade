"""
repo/system.py — 系统配置仓库

包含：
- TradingClock 类（缓存 sysconfig.trdtime 60s；半天/全天判断；is_in_trading_session 协程安全）
- sys_status 单行表; fee_config/reconcile_config/trading_session 已并入 sysconfig

规范：openspec/changes/2026-07-06-layered-architecture-and-strategy-master (分层)
"""
from datetime import datetime, time as dtime
from typing import Optional

from server.db import db_session
from server.models.orm import get_active_sysstatus  # helper 内部已走 Tables API


class TradingClock:
    """交易时段缓存 + 半天判断 (读 sysconfig.trdtime)

    - 内部存 _sessions: list[(time, time)] (从 sysconfig 解析)
    - 缓存 60s, is_in_trading_session 协程安全
    - 半天判定: SysStatus.is_half_day (单行 id=1)
    """
    _sessions: list = []
    _is_half_day: bool = False
    _loaded_at = None
    CACHE_TTL_SEC = 60

    @classmethod
    def _reload(cls):
        from server.services.sysconfig import parse_trdtime, get_trdtime_str
        s = get_trdtime_str()
        cls._sessions = parse_trdtime(s)
        with db_session() as db:
            active = get_active_sysstatus(db)
            cls._is_half_day = bool(active and active.status == "active" and active.is_half_day)
        cls._loaded_at = datetime.now()

    @classmethod
    def _ensure_loaded(cls):
        if (cls._loaded_at is None or
                (datetime.now() - cls._loaded_at).total_seconds() >= cls.CACHE_TTL_SEC):
            cls._reload()

    @classmethod
    def is_in_trading_session(cls, now=None):
        cls._ensure_loaded()
        t = (now or datetime.now()).time()
        for i, (start, end) in enumerate(cls._sessions):
            if start <= t <= end:
                if i > 0 and cls._is_half_day:
                    return False
                return True
        return False

    @classmethod
    def get_session_window(cls):
        cls._ensure_loaded()
        windows = [{"start": s.isoformat(), "end": e.isoformat()} for s, e in cls._sessions]
        return {"windows": windows, "is_half_day": cls._is_half_day}

    @classmethod
    def next_session_start(cls):
        cls._ensure_loaded()
        if not cls._sessions:
            return None
        from datetime import datetime as _dt
        now = _dt.now()
        t = now.time()
        first_start, _ = cls._sessions[0]
        last_end = cls._sessions[-1][1]
        if t < first_start:
            return first_start
        if t > last_end:
            return None
        for i, (start, end) in enumerate(cls._sessions):
            if start <= t <= end:
                if i + 1 < len(cls._sessions):
                    return cls._sessions[i + 1][0]
                return None
            if i + 1 < len(cls._sessions) and end < t < cls._sessions[i + 1][0]:
                return cls._sessions[i + 1][0]
        return None

    @classmethod
    def seconds_until_session(cls):
        """距下一交易时段开始的秒数 (兼容 clock API)

        Returns:
            int: 距 next_session_start 的秒数; 若 next_session_start 为 None (今日已结束), 返回 None
        """
        cls._ensure_loaded()
        from datetime import datetime as _dt, timedelta as _td
        nxt = cls.next_session_start()
        if nxt is None:
            return None
        now = _dt.now()
        target = _dt.combine(now.date(), nxt)
        # 跨天保护: 若 target < now, 视为明天 (next_session_start 应该在当天, 这只是兜底)
        if target < now:
            target = target + _td(days=1)
        return int((target - now).total_seconds())

