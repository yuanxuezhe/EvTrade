"""
guards.py — 交易屏障层（SysStatus 单行宽表, id=1）+ RBAC page_key 守卫

- require_trading_day: 未做日初 → 503 TRADING_DAY_NOT_INIT
- require_trading_session: 非交易时段 → 503 OUTSIDE_TRADING_SESSION
- require_trader: 角色校验（直接复用 auth.deps）
- require_admin: admin 角色校验（users.role 字符串, 保留向后兼容）
- require_page_key: 页面权限校验 (RBAC 角色 → page_keys, 角色 v—roles-module change)

sys_status 为单行宽表 (id=1): 无 "status='active'" 多行概念;
切日判定看 id=1 行的 status 字段 + trd_date 字段。
"""
from datetime import datetime
from fastapi import HTTPException, Depends, Request
from typing import Optional
from sqlalchemy.orm import Session  # noqa: F401  (existing type hint 用)

from server.infra.db import db_session
from server.repo.system import TradingClock, get_active_trd_date, get_active_sysstatus
from server.auth.deps import get_current_user
from server.tables import Row
from server.services.rbac import (
    get_user_role_names,
    get_user_page_keys,
    user_has_page_key,
)


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


def require_trader(current_user: Row = Depends(get_current_user)) -> Row:
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


def require_admin(current_user: Row = Depends(get_current_user)) -> Row:
    """屏障：admin 角色校验（日初处理用）— 保留 users.role 字符串 fallback"""
    if current_user.role != 'admin':
        raise HTTPException(
            status_code=403,
            detail={"code": "FORBIDDEN", "msg": f"角色 {current_user.role} 无权管理"}
        )
    return current_user


# ── RBAC 页面权限守卫 (v—roles-module) ────────────────────────────────────

def require_page_key(page_key: str):
    """FastAPI dep 工厂: 检查当前用户的 role 集合是否含 page_key.

    用法:
        @router.get("/foo")
        def foo(_guard = Depends(require_page_key("trade.t0"))):
            ...

    行为:
      - 任一 role 含 '*' (super_admin 通配) → 通过
      - 查 user_roles → roles → role_permissions 合并 set, page_key ∈ set → 通过
      - 无 role 或 不含 page_key → 403 FORBIDDEN

    兼容性:
      - 当前用户是 admin (users.role 字符串 admin) → 旧逻辑保留 (require_admin 单独用, 本函数不接管)
      - 新 admin 用户 (user_roles 命中 super_admin) → '*' 通配通过
    """
    def _dep(current_user: Row = Depends(get_current_user)) -> Row:
        with db_session() as db:
            keys = get_user_page_keys(db, current_user.id)
            if '*' in keys or page_key in keys:
                return current_user
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "FORBIDDEN",
                    "msg": f"无权访问 {page_key} (当前角色集合不含此页面权限)",
                },
            )
    _dep.__name__ = f"require_page_key_{page_key.replace('.', '_').replace('-', '_')}"
    return _dep