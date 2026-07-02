"""
push/run_handlers.py — push 落库 / 交易日查询的线程池与短连接 helper

REQ-PUSH-006: push 落库在新线程跑（loop.run_in_executor 包裹），不阻塞 listener event loop。
push 链路 trd_date 注入：每次新开 SessionLocal，无状态依赖。
"""
import logging
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)


def _run_handle_push(func: str, row: Dict[str, Any], ts: str) -> Optional[Dict[str, Any]]:
    """push 落库 helper：新线程内跑 SessionLocal + handle_push + commit。

    设计要点：
    - 在新线程中执行（loop.run_in_executor 包裹），不阻塞 push listener 的 event loop
    - SessionLocal 每次新建，独立 session 安全无共享状态
    - 异常向上抛回 await 处，由 listener 捕获并 log
    - handle_push 同步签名不变（向后兼容 test_push_handlers.py 11 用例）
    - 返回 handler 的重组包结果（OrderOut/TradeOut 兼容 dict）
    """
    from server.db import db_session
    from server.services.push.handlers import handle_push
    with db_session() as db:
        result = handle_push(db, func, row, ts)
        db.commit()
        return result


def _resolve_active_trd_date_safe() -> Optional[str]:
    """短连接查当前激活交易日（push 链路注入 trd_date 用）。

    Returns:
        8 位 YYYYMMDD，或 None（未做日初 / DB 异常时）

    设计要点：
    - 每次调用都新开 SessionLocal（无状态依赖，安全）
    - 异常返回 None 而非 raise（不阻塞 push listener 主循环）
    - 不传 row 参数给 ws：返回 None 时不注入 trd_date，前端用 _today_yyyymmdd 兜底
    """
    try:
        from server.db import db_session
        from server.services.guards import resolve_active_trd_date
        with db_session() as db:
            return resolve_active_trd_date(db)
    except Exception as e:
        # 短连接异常（DB 锁 / disconnect）不应中断 push 链路
        log.warning("_resolve_active_trd_date_safe failed: %s", e)
        return None


__all__ = ["_run_handle_push", "_resolve_active_trd_date_safe"]