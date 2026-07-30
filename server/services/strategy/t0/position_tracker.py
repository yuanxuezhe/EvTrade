"""
strategy/t0/position_tracker.py — 日内 T0 敞口跟踪

📌 T0 交易要求 entry/exit 配对，同日内完成
📌 正T: buy entry → sell exit（先买后卖）
📌 倒T: sell entry → buy exit（先卖后买）
📌 每个 model 同时只允许一个 open position
📌 操作计数：每开一个 position 计数 +1（entry 时）
"""
from typing import Dict, List, Optional

from server.services.strategy.t0.models import T0Position


class T0PositionTracker:
    """单一 T0 策略的敞口跟踪器。

    📌 _positions: model_name → T0Position（每个 model 最多一个敞口）
    📌 _operations_today: 当日已执行的做T次数（entry 计数）
    📌 _trd_date: 当前日期（跨日自动清零）
    """

    def __init__(self, strategy_id: int, stock_code: str):
        self.strategy_id = strategy_id
        self.stock_code = stock_code
        self._positions: Dict[str, T0Position] = {}
        self._operations_today: int = 0
        self._trd_date: Optional[str] = None

    def add_position(self, position: T0Position) -> None:
        """新建一个 open position（+1 操作计数）"""
        self._trd_date = position.trd_date
        self._positions[position.signal_model] = position
        self._operations_today += 1

    def close_position(self, model: str) -> Optional[T0Position]:
        """按 model 关闭敞口"""
        return self._positions.pop(model, None)

    def get_position(self, model: str) -> Optional[T0Position]:
        """查询 model 的当前敞口"""
        return self._positions.get(model)

    def get_open_positions(self) -> List[T0Position]:
        """返回所有 open positions"""
        return list(self._positions.values())

    def has_open_position(self, model: str) -> bool:
        """model 是否有 open position"""
        return model in self._positions

    def has_any_open(self) -> bool:
        """是否有任何 open position"""
        return bool(self._positions)

    def close_all(self) -> List[T0Position]:
        """关闭所有敞口（强制平仓）"""
        positions = list(self._positions.values())
        self._positions.clear()
        return positions

    @property
    def operations_today(self) -> int:
        return self._operations_today

    def check_unrealized_loss(self, current_price: float) -> Optional[T0Position]:
        """检查是否有 position 触发止损。

        返浮亏最大的 position（如超过止损阈值），None 表示都安全。
        """
        worst = None
        worst_loss_pct = 0.0
        for pos in self._positions.values():
            loss_pct = self._calc_loss(pos, current_price)
            if loss_pct > worst_loss_pct:
                worst_loss_pct = loss_pct
                worst = pos
        return worst if worst and worst_loss_pct > 0 else None

    @staticmethod
    def _calc_loss(position: T0Position, current_price: float) -> float:
        """计算 position 的亏损幅度（正值=亏损，负值=盈利）"""
        if position.entry_price <= 0:
            return 0.0
        if position.direction == "buy":
            # 正T：买入后跌了 = 亏损
            return (position.entry_price - current_price) / position.entry_price
        else:
            # 倒T：卖出后涨了 = 亏损
            return (current_price - position.entry_price) / position.entry_price

    def reset_day(self, trd_date: str) -> None:
        """跨日重置（强制清空所有敞口 + 计数归零）"""
        if self._trd_date != trd_date:
            self._positions.clear()
            self._operations_today = 0
            self._trd_date = trd_date

    def to_dicts(self) -> List[dict]:
        """序列化用于 WS broadcast"""
        return [
            {
                "direction": p.direction,
                "entry_price": p.entry_price,
                "entry_volume": p.entry_volume,
                "signal_model": p.signal_model,
                "entry_time": p.entry_time,
            }
            for p in self._positions.values()
        ]


__all__ = ["T0PositionTracker"]
