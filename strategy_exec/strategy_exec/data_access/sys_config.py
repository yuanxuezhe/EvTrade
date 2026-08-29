"""
strategy_exec.data_access.sys_config — 直读 EvTrade 共享 sys_config 表

📌 共享 MySQL (EVTRADE_DB_URL). 读 user='0' 系统配置 (与 server/services/sysconfig.py 同一表)
- sys_config.user='0' 的 cfg_key + cfg_val 是系统级配置 (rpc_test_mode / cantrdstktypes 等)
- strategy_exec 与 EvTrade server 共享 MySQL, 可直连读
- 不依赖 server.services.sysconfig (避免跨服务 import 链)

缓存策略:
- 内存缓存 5s (避免每次 fetch_his_bars 都打 DB)
- 错误/缺失 → 返 default (不抛)
- 用 SQLAlchemy text + engine (复用 data_access/db.py)
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

log = logging.getLogger(__name__)

_CACHE_TTL_S = 5.0

# 内存缓存 (单进程足够; strategy_exec 是单实例)
_cache: dict = {}              # {key: (val, ts)}
_cache_lock_placeholder: bool = True  # 占位, strategy_exec 单线程 async, 不需 lock


def read(key: str, default: Any = 0) -> Any:
    """读 sys_config.user='0' AND cfg_key=key, 5s 缓存.

    Returns:
        cfg_val 字符串 (sys_config 表存的是 VARCHAR/TEXT)
        缺失/错误 → default

    Examples:
        read('rpc_test_mode', 0)        # '0' or '1'
        read('his_hq_test_mode', '0')  # '0' or '1'
    """
    now = time.time()
    cached = _cache.get(key)
    if cached is not None:
        val, ts = cached
        if (now - ts) < _CACHE_TTL_S:
            return val

    val = _db_read(key, default)
    _cache[key] = (val, now)
    return val


def invalidate(key: Optional[str] = None) -> None:
    """清除缓存 (用于 set_value 后立即生效).

    Args:
        key: 清除指定 key, None 清全部
    """
    global _cache
    if key is None:
        _cache.clear()
    else:
        _cache.pop(key, None)


def _db_read(key: str, default: Any) -> Any:
    """直连 DB 读 sys_config (策略: 失败返 default, 不抛)"""
    try:
        from sqlalchemy import text
        from strategy_exec.data_access.db import get_engine

        engine = get_engine()
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT cfg_val FROM sys_config WHERE `user`='0' "
                    "AND cfg_key=:k LIMIT 1"
                ),
                {"k": key},
            ).first()
        if row is None or row[0] is None:
            return default
        return row[0]
    except Exception as e:  # noqa: BLE001
        log.warning("[sys_config.read] key=%s read failed (return default=%r): %s",
                    key, default, e)
        return default


def reset_for_test() -> None:
    """测试用: 清缓存 + 重置 (单测可放心调)"""
    global _cache
    _cache = {}


__all__ = ["read", "invalidate", "reset_for_test"]