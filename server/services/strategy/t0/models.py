"""
strategy/t0/models.py — T0 策略参数和运行时数据结构

📌 T0StrategyParams: 全部可配置参数（JSON 序列化存入 strategy.t0_params）
📌 T0Position: 日内 T0 敞口跟踪
📌 T0Signal: 检测到的交易信号
📌 T0EvaluateResult: evaluate_tick 单次输出
"""
import json
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple


# ─────────────── 子参数 ───────────────

@dataclass
class T0VWAPParams:
    """VWAP 乖离率回归模型参数"""
    buy_deviation_low: float = 0.015       # 向下偏离 1.5% 触发买入
    buy_deviation_high: float = 0.025      # 向下偏离 2.5% 强买入
    sell_deviation_low: float = 0.02       # 向上偏离 2% 触发卖出
    sell_deviation_high: float = 0.03      # 向上偏离 3% 强卖出
    close_deviation: float = 0.008         # 回归至 0.8% 内触发平仓
    require_kline_signal: bool = True      # 是否需要 5min K 线确认


@dataclass
class T0OpeningParams:
    """开盘30分钟冲高/急跌模型参数"""
    surge_threshold: float = 0.03          # 冲高超过 3%
    drop_threshold: float = 0.025          # 急跌超过 2.5%
    sell_window_start: int = 575           # 09:35（分钟数）
    sell_window_end: int = 585             # 09:45
    opening_period_minutes: int = 30       # 开盘后多久内有效


@dataclass
class T0BollingerParams:
    """5分钟布林线触轨模型参数"""
    period: int = 20                       # 布林线周期
    std_mult: float = 2.0                  # 标准差倍数
    rsi_period: int = 6                    # RSI 周期
    rsi_oversold: float = 20.0             # RSI < 20 超卖
    rsi_overbought: float = 80.0           # RSI > 80 超买


@dataclass
class T0RiskParams:
    """日内风控参数"""
    stop_loss_pct: float = 0.015           # 单笔止损 1.5%
    time_cutoff: int = 870                 # 14:30（分钟数）
    max_operations_per_day: int = 2        # 单标日限 2 次


# ─────────────── 组合参数 ───────────────

@dataclass
class T0StrategyParams:
    """T0 策略完整参数集（JSON 序列化存入 strategy.t0_params）"""
    test_mode: bool = True                     # True=仅信号，False=实盘
    models_enabled: List[str] = field(default_factory=lambda: ["vwap", "opening", "bollinger"])
    vwap: T0VWAPParams = field(default_factory=T0VWAPParams)
    opening: T0OpeningParams = field(default_factory=T0OpeningParams)
    bollinger: T0BollingerParams = field(default_factory=T0BollingerParams)
    risk: T0RiskParams = field(default_factory=T0RiskParams)
    signal_volume: int = 100                   # 单次信号默认成交量（股）
    signal_cooldown: int = 120                 # 信号冷却秒数（防连续触发）

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "T0StrategyParams":
        if not d:
            return cls()
        vwap_d = d.get("vwap", {})
        opening_d = d.get("opening", {})
        bb_d = d.get("bollinger", {})
        risk_d = d.get("risk", {})
        return cls(
            test_mode=d.get("test_mode", True),
            models_enabled=d.get("models_enabled", ["vwap", "opening", "bollinger"]),
            vwap=T0VWAPParams(**vwap_d),
            opening=T0OpeningParams(**opening_d),
            bollinger=T0BollingerParams(**bb_d),
            risk=T0RiskParams(**risk_d),
            signal_volume=d.get("signal_volume", 100),
            signal_cooldown=d.get("signal_cooldown", 120),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_json(cls, s: str) -> "T0StrategyParams":
        if not s or s in ("null", ""):
            return cls()
        try:
            return cls.from_dict(json.loads(s))
        except (json.JSONDecodeError, TypeError):
            return cls()


# ─────────────── 运行时数据 ───────────────

@dataclass
class T0Position:
    """日内 T0 敞口（entry/exit 配对）"""
    direction: str               # 'buy' (正T) 或 'sell' (倒T)
    entry_price: float
    entry_volume: int
    entry_time: float            # epoch 秒
    signal_model: str            # 'vwap' / 'opening' / 'bollinger'
    strategy_id: int
    stock_code: str
    trd_date: str


@dataclass
class T0Signal:
    """检测到的交易信号"""
    signal_type: str             # 'vwap_buy' / 'vwap_sell' / 'opening_buy' / 'opening_sell' / 'bb_buy' / 'bb_sell' / 'close_position'
    model: str                   # 'vwap' / 'opening' / 'bollinger'
    direction: str               # 'buy' / 'sell'
    price: float
    volume: int
    reason: str                  # 中文描述
    strength: float = 0.5        # 0.0-1.0 信号强度
    timestamp: float = 0.0


@dataclass
class T0EvaluateResult:
    """evaluate_tick 单次调用输出"""
    strategy_id: int
    signals: List[T0Signal] = field(default_factory=list)
    actions_taken: List[Dict[str, Any]] = field(default_factory=list)
    open_positions: List[Dict[str, Any]] = field(default_factory=list)
    vwap: Optional[float] = None
    bb_upper: Optional[float] = None
    bb_middle: Optional[float] = None
    bb_lower: Optional[float] = None
    current_deviation: Optional[float] = None
    audit_ids: List[int] = field(default_factory=list)
    order_nos: List[str] = field(default_factory=list)
