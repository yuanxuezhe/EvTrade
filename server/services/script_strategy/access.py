"""
server/services/script_strategy/access.py — 策略可见性/权限判定

职责单一: 显式 is_public 判定, 替代旧的"派生自公开脚本即放行"隐式规则。
- strategy_is_public / public_view: 策略是否公开 + 他人公开策略的精简视图
  (只含身份/状态/绑定标的, 不含 script 源码 / params_schema / best_params)
- resolve_strategy: 解析策略 → owner/admin 返回完整行; 他人仅公开返回; 他人私有/不存在 → None
- require_backtest_access: 回测/批次/重测的严格 owner 门禁
  (他人公开 → BACKTEST_FORBIDDEN; 他人私有/不存在 → NO_STRATEGY, 不泄漏存在性)
- require_strategy_order_access: 母单 owner 门禁 (三档: owner 通行 / 他人公开 403 / 不存在 404)

策略模块 = 纯回测: 实盘入口已通过母单 (strategy_order) 重启。
"""
from typing import Any, Dict, Optional

from server.services.script_strategy.errors import StrategyError


def strategy_is_public(strat) -> bool:
    """策略行是否公开 (strategy.is_public == 1)."""
    return bool(getattr(strat, "_data", {}).get("is_public", 0))


def public_view(strat) -> Dict[str, Any]:
    """他人公开策略的精简视图 (列表/精简详情). 不含 script/best_params."""
    d = getattr(strat, "_data", {})
    return {
        "strategy_id": d.get("strategy_id"),
        "user_id": d.get("user_id"),
        "script_id": d.get("script_id"),
        "name": d.get("name", ""),
        "status": d.get("status", "draft"),
        "is_public": True,
        "stock_code": d.get("stock_code"),
    }


def resolve_strategy(strategy_id: int, user_id: int, is_admin: bool = False) -> Optional[Any]:
    """解析策略: owner/admin 返回完整行; 他人仅公开策略返回; 他人私有/不存在 → None."""
    from server.tables import Strategy
    row = Strategy.query_one(strategy_id=strategy_id)
    if row is None:
        return None
    d = getattr(row, "_data", {})
    if is_admin or d.get("user_id") == user_id:
        return row
    if strategy_is_public(row):
        return row
    return None


def require_backtest_access(strategy_id: int, user_id: int, is_admin: bool = False):
    """回测/批次/重测门禁: 仅 owner/admin 可访问.

    Raises:
        StrategyError: 他人公开 → BACKTEST_FORBIDDEN; 他人私有/不存在 → NO_STRATEGY
    """
    from server.tables import Strategy
    row = Strategy.query_one(strategy_id=strategy_id)
    if row is None:
        raise StrategyError("NO_STRATEGY", f"strategy_id {strategy_id} 不存在或无权访问")
    d = getattr(row, "_data", {})
    if is_admin or d.get("user_id") == user_id:
        return row
    if strategy_is_public(row):
        raise StrategyError("BACKTEST_FORBIDDEN", "他人公开策略不可回测 (仅本人可回测)")
    raise StrategyError("NO_STRATEGY", f"strategy_id {strategy_id} 不存在或无权访问")


def require_strategy_order_access(strategy_id: int, user_id: int, is_admin: bool = False):
    """母单门禁: 仅策略 owner/admin 可建/启停母单.

    与 require_backtest_access 行为一致 — 母单是本人对本人策略的实盘操作,
    他人公开策略不可被代建/代启 (公开 = 仅回测参考, 不含实盘托管).

    Raises:
        StrategyError: 他人公开 → FORBIDDEN; 他人私有/不存在 → NO_STRATEGY
    """
    from server.tables import Strategy
    row = Strategy.query_one(strategy_id=strategy_id)
    if row is None:
        raise StrategyError("NO_STRATEGY", f"strategy_id {strategy_id} 不存在或无权访问")
    d = getattr(row, "_data", {})
    if is_admin or d.get("user_id") == user_id:
        return row
    if strategy_is_public(row):
        raise StrategyError("FORBIDDEN", "他人公开策略不可建/启停母单 (仅本人可实盘)")
    raise StrategyError("NO_STRATEGY", f"strategy_id {strategy_id} 不存在或无权访问")


__all__ = [
    "strategy_is_public", "public_view", "resolve_strategy",
    "require_backtest_access", "require_strategy_order_access",
]
