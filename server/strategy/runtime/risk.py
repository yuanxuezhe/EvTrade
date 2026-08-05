"""
server/strategy/runtime/risk.py — 风控守卫 (v10)

策略执行前的风控检查:
- 单笔金额上限: 单笔 buy 金额 ≤ limit (默认 50,000)
- 累计笔数: 每日累计笔数 ≤ limit (默认 100)
- 最大持仓: 单只持仓金额 ≤ limit (默认 100,000)
- 强平阈值: 总亏损 ≥ -limit (默认 -10,000) → 自动平仓

设计原则:
- 风控配置存 strategy_task.risk_config (JSON)
- LiveRunner + BacktestEngine 都调 check_before_order()
- 风控拒绝时: 写 audit + 触发 INFO 信号, 不抛异常 (脚本仍能跑)

返回值: (allowed: bool, reason: str)
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple


# 默认风控配置 (用户可覆盖 via task.risk_config)
DEFAULT_RISK_CONFIG = {
    "max_order_amount": 50_000.0,      # 单笔金额上限
    "max_daily_trades": 100,            # 每日累计笔数上限
    "max_position_amount": 100_000.0,   # 单只最大持仓金额
    "max_drawdown": -10_000.0,          # 总亏损阈值 (触发强平)
    "enabled": True,                    # 全局开关
}


class RiskChecker:
    """单实例持有风控配置 + 累计状态 (每 task 一个)

    Args:
        risk_config: 任务级风控配置 (覆盖默认)
        initial_cash: 起始资金
    """

    def __init__(self, risk_config: Optional[Dict[str, Any]] = None, initial_cash: float = 100_000.0):
        cfg = dict(DEFAULT_RISK_CONFIG)
        if risk_config:
            cfg.update({k: v for k, v in risk_config.items() if k in cfg})
        self.cfg = cfg
        self.initial_cash = initial_cash
        self._daily_trades: Dict[str, int] = {}  # trd_date -> count

    def check_before_order(
        self,
        *,
        side: str,                  # "BUY" / "SELL"
        price: float,
        qty: float,
        current_position: int,      # 当前持仓 (正数持多, 负数持空, 0 空仓)
        current_cash: float,        # 当前现金
        current_position_value: float = 0.0,  # 当前持仓市值 (price * qty)
        trd_date: str = "",         # 交易日 YYYYMMDD
    ) -> Tuple[bool, str]:
        """下单前风控检查

        Returns:
            (True, "") - 允许下单
            (False, reason) - 拒绝 + 原因
        """
        if not self.cfg.get("enabled", True):
            return True, ""

        order_amount = abs(price * qty)

        # 单笔金额上限
        if order_amount > self.cfg["max_order_amount"]:
            return False, (
                f"风控拒单: 单笔金额 ¥{order_amount:,.0f} "
                f"超过上限 ¥{self.cfg['max_order_amount']:,.0f}"
            )

        # 累计笔数上限 (按交易日)
        if trd_date:
            today_count = self._daily_trades.get(trd_date, 0)
            if today_count >= self.cfg["max_daily_trades"]:
                return False, (
                    f"风控拒单: 交易日 {trd_date} 已累计 {today_count} 笔, "
                    f"超过上限 {self.cfg['max_daily_trades']}"
                )

        # 最大持仓金额 (buy 时检查预估 post-buy 持仓)
        if side == "BUY":
            post_pos_value = current_position_value + order_amount
            if post_pos_value > self.cfg["max_position_amount"]:
                return False, (
                    f"风控拒单: 买后持仓 ¥{post_pos_value:,.0f} "
                    f"超过上限 ¥{self.cfg['max_position_amount']:,.0f}"
                )

        return True, ""

    def check_max_drawdown(self, total_pnl: float) -> Tuple[bool, str]:
        """检查强平阈值 (亏损 ≥ max_drawdown)

        Returns:
            (True, "") - 未触阈值
            (False, reason) - 触发强平
        """
        if not self.cfg.get("enabled", True):
            return True, ""
        if total_pnl <= self.cfg["max_drawdown"]:
            return False, (
                f"风控强平: 总亏损 ¥{total_pnl:,.0f} "
                f"达阈值 ¥{self.cfg['max_drawdown']:,.0f}"
            )
        return True, ""

    def record_trade(self, trd_date: str = "") -> None:
        """下单成功后调用, 计入日累计"""
        if trd_date:
            self._daily_trades[trd_date] = self._daily_trades.get(trd_date, 0) + 1

    def stats(self) -> Dict[str, Any]:
        """返回当前状态 (debug 用)"""
        return {
            "cfg": dict(self.cfg),
            "daily_trades": dict(self._daily_trades),
        }


__all__ = ["RiskChecker", "DEFAULT_RISK_CONFIG"]