"""
strategy — 4 张 ORM 模型（change strategy_trade）

📖 详细 spec：openspec/specs/strategy/spec.md
📖 数据契约：openspec/specs/data-model/spec.md §2.4

设计要点：
- Strategy：总表（管理策略的顶层实体），含 type 字段区分 general / t0
- StrategyRegime：参数集，多对一 Strategy，含 priority + 标志约束 + 底仓 override + clear_position
- StrategyGrid：网格，多对一 Regime，含 direction + step_offset + 触发计数 + 优先级
- StrategyAudit：触发审计，每次评估无论触发与否写一行

JSON 字段（required_flags / exclude_flags / flags_active / action_payload）：
  写入：Python list/dict → JSON string
  读取：JSON string → Python list/dict（_json_loads 防御空字符串）
"""
from sqlalchemy import (
    Column, Integer, String, Float, Text, DateTime, Boolean,
    Index, ForeignKey,
)
from sqlalchemy.orm import relationship

from server.db import Base
from server.utils.time import _utcnow


# ─────────────── JSON helper ───────────────

import json as _json


def _json_dumps(value) -> str:
    """Python 对象 → JSON 字符串（None → 'null'，空 list → '[]'）"""
    if value is None:
        return "null"
    return _json.dumps(value, ensure_ascii=False, sort_keys=True)


def _json_loads(value: str):
    """JSON 字符串 → Python 对象（None / 空字符串 / 解析失败防御）"""
    if not value:
        return [] if value in (None, "", "null", "[]") else []
    try:
        return _json.loads(value)
    except (ValueError, TypeError):
        return []


# ─────────────── Strategy（总表） ───────────────


class Strategy(Base):
    """管理策略的总表（顶层实体）。

    📖 详见 `openspec/specs/strategy/spec.md` REQ-STRAT-001
    📌 type 字段（REQ-STRAT-001 §Scenario type 取值校验）：
       - 'general'：普通网格策略
       - 't0'：T0 策略（其产生的订单 user_def=str(id)，由 t0-stats 等端点 JOIN 识别）
    📌 同 (user_id, stock_code, type) 唯一 active（应用层校验，DB 层不强制）
    """
    __tablename__ = "strategy"
    __table_args__ = (
        Index("ix_strategy_user_status", "user_id", "status"),
        Index("ix_strategy_type", "type"),
        Index("ix_strategy_stock", "user_id", "stock_code"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False)
    stock_code = Column(String(16), nullable=False)
    type = Column(String(16), nullable=False, default="general")
    reference_price = Column(Float, nullable=False, default=0.0)
    status = Column(String(16), nullable=False, default="active")  # active / paused / stopped / finished
    base_volume = Column(Integer, nullable=False, default=0)
    note = Column(String(255), nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    regimes = relationship(
        "StrategyRegime",
        back_populates="strategy",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="StrategyRegime.priority.desc(), StrategyRegime.id",
    )


# ─────────────── StrategyRegime（参数集） ───────────────


class StrategyRegime(Base):
    """策略参数集（多对一 Strategy）。

    📖 详见 `openspec/specs/strategy/spec.md` REQ-STRAT-003 / 005
    📌 匹配语义：required_flags AND ⊆ active_flags，exclude_flags ∩ active_flags = ∅
    📌 base_volume = NULL 时继承 strategy.base_volume；非 NULL 时 override
    📌 clear_position = True 时该 regime 触发 plan_clear（全卖含底仓，唯一合法打破底仓路径）
    """
    __tablename__ = "strategy_regime"
    __table_args__ = (
        Index("ix_regime_strategy_priority", "strategy_id", "priority"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_id = Column(
        Integer,
        ForeignKey("strategy.id", ondelete="CASCADE"),
        nullable=False,
    )
    name = Column(String(64), nullable=False)
    priority = Column(Integer, nullable=False, default=0)
    required_flags = Column(Text, nullable=False, default="[]")  # JSON list[str]
    exclude_flags = Column(Text, nullable=False, default="[]")   # JSON list[str]
    base_volume = Column(Integer, nullable=True)                  # NULL = inherit strategy.base_volume
    clear_position = Column(Boolean, nullable=False, default=False)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    strategy = relationship("Strategy", back_populates="regimes")
    grids = relationship(
        "StrategyGrid",
        back_populates="regime",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="StrategyGrid.priority.desc(), StrategyGrid.id",
    )

    def get_required_flags(self) -> list:
        return _json_loads(self.required_flags)

    def get_exclude_flags(self) -> list:
        return _json_loads(self.exclude_flags)

    def set_required_flags(self, value: list) -> None:
        self.required_flags = _json_dumps(value)

    def set_exclude_flags(self, value: list) -> None:
        self.exclude_flags = _json_dumps(value)


# ─────────────── StrategyGrid（网格） ───────────────


class StrategyGrid(Base):
    """策略网格（多对一 StrategyRegime）。

    📖 详见 `openspec/specs/strategy/spec.md` REQ-STRAT-004 / 005
    📌 trigger_price = reference_price + step_offset（冗余存储，查询时避免 JOIN）
    📌 direction：'buy' / 'sell'
    📌 step_offset：相对 reference_price 的偏移（正=向上 负=向下）
    📌 fired_count 累计触发次数（达 max_fires 后不再触发；None=不限）
    """
    __tablename__ = "strategy_grid"
    __table_args__ = (
        Index("ix_grid_regime", "regime_id"),
        Index("ix_grid_regime_dir", "regime_id", "direction"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    regime_id = Column(
        Integer,
        ForeignKey("strategy_regime.id", ondelete="CASCADE"),
        nullable=False,
    )
    direction = Column(String(8), nullable=False)  # 'buy' / 'sell'
    step_offset = Column(Float, nullable=False, default=0.0)
    trigger_price = Column(Float, nullable=False, default=0.0)  # reference_price + step_offset
    volume = Column(Integer, nullable=False, default=0)
    max_fires = Column(Integer, nullable=True)  # NULL = 不限
    fired_count = Column(Integer, nullable=False, default=0)
    enabled = Column(Boolean, nullable=False, default=True)
    priority = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    regime = relationship("StrategyRegime", back_populates="grids")


# ─────────────── StrategyAudit（触发审计） ───────────────


class StrategyAudit(Base):
    """策略触发审计日志（每次评估无论是否触发都写一行）。

    📖 详见 `openspec/specs/strategy/spec.md` REQ-STRAT-006 §audit
    📌 trigger_type:
       - 'grid_buy' / 'grid_sell' / 'clear' / 'manual_clear'
       - 'regime_switch' / 'regime_cooldown'
       - 'no_match' / 'no_action'
    📌 reject_reason（仅 grid_rejected 时填）：
       - 'base_floor_protected' / 'max_fires_reached' / 'grid_cooldown'
    """
    __tablename__ = "strategy_audit"
    __table_args__ = (
        Index("ix_audit_strategy_date", "strategy_id", "trd_date", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_id = Column(
        Integer,
        ForeignKey("strategy.id", ondelete="CASCADE"),
        nullable=False,
    )
    regime_id = Column(Integer, nullable=True)  # 不强制 FK（regime 可能已被删，但审计需保留）
    trd_date = Column(String(8), nullable=False)  # YYYYMMDD
    trigger_type = Column(String(32), nullable=False)
    flags_active = Column(Text, nullable=False, default="[]")  # JSON list[str]
    current_price = Column(Float, nullable=True)
    position_vol = Column(Integer, nullable=True)
    base_volume = Column(Integer, nullable=True)
    action_payload = Column(Text, nullable=True)  # JSON dict 或 NULL
    order_no = Column(String(8), nullable=True)
    reject_reason = Column(String(255), nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)

    def get_flags_active(self) -> list:
        return _json_loads(self.flags_active)

    def set_flags_active(self, value: list) -> None:
        self.flags_active = _json_dumps(value)

    def get_action_payload(self):
        if not self.action_payload:
            return None
        try:
            return _json.loads(self.action_payload)
        except (ValueError, TypeError):
            return None

    def set_action_payload(self, value) -> None:
        self.action_payload = _json_dumps(value) if value is not None else None