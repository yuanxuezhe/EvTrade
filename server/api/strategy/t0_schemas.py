"""
api/strategy/t0_schemas.py — T0 策略 API Pydantic schemas

约定：单 schema/实体，orm_mode=True。JSON 字段用 validator 兼容 ORM 原始字符串。
"""
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, validator


class _OrmConfig(BaseModel):
    class Config:
        orm_mode = True


# ─────────────── 参数子 schema ───────────────

class T0VWAPParamSchema(BaseModel):
    buy_deviation_low: float = 0.015
    buy_deviation_high: float = 0.025
    sell_deviation_low: float = 0.02
    sell_deviation_high: float = 0.03
    close_deviation: float = 0.008
    require_kline_signal: bool = True


class T0OpeningParamSchema(BaseModel):
    surge_threshold: float = 0.03
    drop_threshold: float = 0.025
    sell_window_start: int = 575       # 09:35
    sell_window_end: int = 585         # 09:45
    opening_period_minutes: int = 30


class T0BollingerParamSchema(BaseModel):
    period: int = 20
    std_mult: float = 2.0
    rsi_period: int = 6
    rsi_oversold: float = 20.0
    rsi_overbought: float = 80.0


class T0RiskParamSchema(BaseModel):
    stop_loss_pct: float = 0.015
    time_cutoff: int = 870             # 14:30
    max_operations_per_day: int = 2


# ─────────────── 创建 / 更新 ───────────────

class T0StrategyCreate(BaseModel):
    stock_code: str
    reference_price: float = 0.0
    base_volume: int = 0
    note: str = ""
    test_mode: bool = True
    models_enabled: List[str] = ["vwap", "opening", "bollinger"]
    signal_volume: int = 100
    signal_cooldown: int = 120
    vwap_params: T0VWAPParamSchema = T0VWAPParamSchema()
    opening_params: T0OpeningParamSchema = T0OpeningParamSchema()
    bollinger_params: T0BollingerParamSchema = T0BollingerParamSchema()
    risk_params: T0RiskParamSchema = T0RiskParamSchema()


class T0StrategyUpdate(BaseModel):
    status: Optional[str] = None
    base_volume: Optional[int] = None
    note: Optional[str] = None
    test_mode: Optional[bool] = None
    models_enabled: Optional[List[str]] = None
    signal_volume: Optional[int] = None
    signal_cooldown: Optional[int] = None
    vwap_params: Optional[T0VWAPParamSchema] = None
    opening_params: Optional[T0OpeningParamSchema] = None
    bollinger_params: Optional[T0BollingerParamSchema] = None
    risk_params: Optional[T0RiskParamSchema] = None


class T0StrategyOut(_OrmConfig):
    id: int
    user_id: int
    stock_code: str
    type: str
    reference_price: float
    status: str
    base_volume: int
    note: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    t0_params: Optional[Dict[str, Any]] = None

    @validator("t0_params", pre=True)
    def _parse_t0_params(cls, v):
        if not v or v in ("null", ""):
            return None
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return None
        return v


# ─────────────── 信号 / 持仓 ───────────────

class T0SignalRecord(BaseModel):
    strategy_id: int
    signal_type: str
    model: str
    direction: str
    price: float
    volume: int = 0
    reason: str
    strength: float = 0.5
    order_no: Optional[str] = None
    reject_reason: Optional[str] = None
    timestamp: Optional[datetime] = None


class T0PositionRecord(BaseModel):
    direction: str
    entry_price: float
    entry_volume: int
    signal_model: str
    entry_time: str


class ControlRequest(BaseModel):
    action: str  # pause / resume / stop


__all__ = [
    "T0VWAPParamSchema", "T0OpeningParamSchema",
    "T0BollingerParamSchema", "T0RiskParamSchema",
    "T0StrategyCreate", "T0StrategyUpdate", "T0StrategyOut",
    "T0SignalRecord", "T0PositionRecord", "ControlRequest",
]
