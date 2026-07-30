"""
strategy/t0/risk_control.py — T0 日内风控检查

📌 1. 止损: 单笔亏损 > stop_loss_pct → 强制平仓
📌 2. 时间截断: ≥ 14:30 强制全部平仓，不接受新信号
📌 3. 日限: 操作次数 > max_operations_per_day → 跳过新信号
📌 4. 底仓保护: 做T数量 ≤ position_vol - base_volume，整手向下取整
"""
from typing import Optional

from server.services.strategy.t0.models import T0Position, T0RiskParams

LOT_SIZE = 100  # A 股整手单位


class T0RiskController:
    """T0 风控控制器（纯方法，无状态）"""

    def __init__(self, params: T0RiskParams):
        self._params = params

    def should_stop_loss(self, position: T0Position,
                         current_price: float) -> bool:
        """position 是否触及止损"""
        loss_pct = self._calc_loss(position, current_price)
        return loss_pct >= self._params.stop_loss_pct

    def is_past_cutoff(self, current_time_minutes: int) -> bool:
        """是否已超过时间截断（14:30）"""
        return current_time_minutes >= self._params.time_cutoff

    def should_force_close_all(self, current_time_minutes: int) -> bool:
        """是否到了强制全部平仓时间"""
        return current_time_minutes >= self._params.time_cutoff

    def can_open_position(self, operations_today: int) -> bool:
        """是否还能开新 position（未达日限）"""
        return operations_today < self._params.max_operations_per_day

    @staticmethod
    def calculate_trade_volume(
        position_vol: int,
        base_volume: int,
        signal_volume: int,
    ) -> int:
        """计算实际可做 T 的数量。

        T0 可用 = position_vol - base_volume（不可穿透底仓）
        取 min(signal_volume, available)，整手向下
        """
        available = max(0, position_vol - base_volume)
        if available <= 0:
            return 0
        vol = min(signal_volume, available)
        vol = (vol // LOT_SIZE) * LOT_SIZE
        return vol

    @staticmethod
    def _calc_loss(position: T0Position, current_price: float) -> float:
        """position 亏损幅度（正值=亏损）"""
        if position.entry_price <= 0:
            return 0.0
        if position.direction == "buy":
            return (position.entry_price - current_price) / position.entry_price
        else:
            return (current_price - position.entry_price) / position.entry_price

    @property
    def params(self) -> T0RiskParams:
        return self._params


__all__ = ["T0RiskController", "LOT_SIZE"]
