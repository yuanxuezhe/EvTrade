"""
guards.py — 交易屏障层（SysStatus 单行宽表, id=1）

- require_trading_day: 未做日初 → 503 TRADING_DAY_NOT_INIT
- require_trading_session: 非交易时段 → 503 OUTSIDE_TRADING_SESSION
- require_trader: 角色校验（直接复用 auth.deps）
- require_admin: admin 角色校验

sys_status 为单行宽表 (id=1): 无 "status='active'" 多行概念;
切日判定看 id=1 行的 status 字段 + trd_date 字段。
"""
from datetime import datetime
from fastapi import HTTPException, Depends
from typing import Optional
from sqlalchemy.orm import Session

from server.db import db_session
from server.models.orm import SysStatus, get_active_trd_date, get_active_sysstatus
from server.models.user import User
from server.repo.system import TradingClock
from server.auth.deps import get_current_user


def resolve_active_trd_date(db: Session) -> Optional[str]:
    """返回当前激活的交易日 (8 位数字字符串)，未激活返回 None

    SysStatus 单行 (id=1), 通过 ORM helper 实现。
    """
    return get_active_trd_date(db)


def resolve_default_trd_date(db: Session) -> str:
    """默认查询日期：已激活 → active.trd_date，否则 MAX(trd_date)，否则今日

    已激活判定走 SysStatus 单行 (id=1)。
    """
    trd = get_active_trd_date(db)
    if trd:
        return trd
    # 兜底：取本地表 MAX
    # 注意：positions 是当前快照（按 stock_code 唯一），无 trd_date 列，
    # 不能进这个循环。其余 3 张表都有 trd_date。
    from sqlalchemy import text
    for table in ("orders", "trades", "reconcile_report"):
        r = db.execute(text(f"SELECT MAX(trd_date) FROM {table}")).first()
        if r and r[0]:
            return r[0]
    return datetime.now().strftime('%Y%m%d')


async def require_trading_day() -> str:
    """交易屏障：未做日初 → 拒绝下单/撤单（但不影响查询）

    返回的 trd_date 通过 Depends 注入到 handler 的 trd_date 参数。
    """
    with db_session() as db:
        trd = resolve_active_trd_date(db)
        if not trd:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "TRADING_DAY_NOT_INIT",
                    "msg": "未做日初处理，无法交易",
                    "redirect": "/admin/sys-status",
                }
            )
        return trd


async def require_trading_session() -> None:
    """屏障：非交易时段 → 拒绝下单/撤单"""
    if not TradingClock.is_in_trading_session():
        win = TradingClock.get_session_window()
        raise HTTPException(
            status_code=503,
            detail={
                "code": "OUTSIDE_TRADING_SESSION",
                "msg": f"非交易时段，仅可查询。当前时间 {datetime.now().strftime('%H:%M:%S')}",
                "current_time": datetime.now().isoformat(),
                "session_window": win,
            }
        )


def require_trader(current_user: User = Depends(get_current_user)) -> User:
    """屏障：只有 trader/admin 角色可下单/撤单

    直接复用 auth.deps.get_current_user 取用户对象。
    返回 User 而非 str，方便 handler 取 username。
    """
    if current_user.role not in ('trader', 'admin'):
        raise HTTPException(
            status_code=403,
            detail={"code": "FORBIDDEN", "msg": f"角色 {current_user.role} 无权交易"}
        )
    return current_user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """屏障：admin 角色校验（日初处理用）"""
    if current_user.role != 'admin':
        raise HTTPException(
            status_code=403,
            detail={"code": "FORBIDDEN", "msg": f"角色 {current_user.role} 无权管理"}
        )
    return current_user
