"""
strategy — repository 层（DB CRUD）

📖 详见 openspec/specs/strategy/spec.md REQ-STRAT-008
职责：封装 SQLAlchemy 操作，service / api 层不直接写 query。
约定：
  - 所有函数接 db: Session 作第一个参数（由 caller 管理事务）
  - 不在内部 commit（让 caller 决定事务边界，POST 端点统一 commit）
  - JSON 字段（required_flags / exclude_flags）通过 Regime.set_required_flags() 等 setter 写入
"""
from typing import List, Optional

from sqlalchemy.orm import Session

from server.services.strategy.models import (
    Strategy,
    StrategyRegime,
    StrategyGrid,
    StrategyAudit,
)
from server.services.strategy.t0.models import T0StrategyParams


# ─────────────── Strategy CRUD ───────────────


def create_strategy(db: Session, user_id: int, **kwargs) -> Strategy:
    """创建策略 + 嵌套 regimes + grids（单事务，调用方 commit）

    kwargs: stock_code, type, reference_price, base_volume, note, status
            regimes: list[dict] 含 grids: list[dict]
    """
    s = Strategy(
        user_id=user_id,
        stock_code=kwargs["stock_code"],
        type=kwargs.get("type", "general"),
        reference_price=kwargs.get("reference_price", 0.0),
        status=kwargs.get("status", "active"),
        base_volume=kwargs.get("base_volume", 0),
        note=kwargs.get("note", ""),
    )
    db.add(s)
    db.flush()  # 取 s.id
    for reg_dict in kwargs.get("regimes", []):
        create_regime(db, s.id, **reg_dict)
    return s


def get_strategy(db: Session, strategy_id: int, user_id: Optional[int] = None) -> Optional[Strategy]:
    q = db.query(Strategy).filter(Strategy.id == strategy_id)
    if user_id is not None:
        q = q.filter(Strategy.user_id == user_id)
    return q.first()


def list_strategies(
    db: Session, user_id: int, status: Optional[str] = None, type_: Optional[str] = None
) -> List[Strategy]:
    q = db.query(Strategy).filter(Strategy.user_id == user_id)
    if status:
        q = q.filter(Strategy.status == status)
    if type_:
        q = q.filter(Strategy.type == type_)
    return q.order_by(Strategy.updated_at.desc()).all()


def update_strategy(db: Session, strategy: Strategy, **kwargs) -> Strategy:
    """更新策略基本信息（不修改嵌套 regimes/grids，由 caller 单独处理）"""
    for field in ("stock_code", "type", "reference_price", "status", "base_volume", "note", "t0_params"):
        if field in kwargs:
            setattr(strategy, field, kwargs[field])
    return strategy


def save_t0_params(db: Session, strategy_id: int, params: T0StrategyParams) -> Strategy:
    """保存 T0 策略参数到 strategy.t0_params JSON 列"""
    s = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    if s:
        s.t0_params = params.to_json()
        db.flush()
    return s


def get_t0_params(db: Session, strategy_id: int) -> T0StrategyParams:
    """读取 T0 策略参数（无则返默认）"""
    s = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    if s and s.t0_params:
        return T0StrategyParams.from_json(s.t0_params)
    return T0StrategyParams()


def delete_strategy(db: Session, strategy: Strategy) -> None:
    """删 Strategy + 级联删 regimes/grids/audits（依赖 FK ON DELETE CASCADE）"""
    db.delete(strategy)
    db.flush()


# ─────────────── StrategyRegime CRUD ───────────────


def create_regime(db: Session, strategy_id: int, **kwargs) -> StrategyRegime:
    r = StrategyRegime(
        strategy_id=strategy_id,
        name=kwargs["name"],
        priority=kwargs.get("priority", 0),
        base_volume=kwargs.get("base_volume"),
        clear_position=kwargs.get("clear_position", False),
        enabled=kwargs.get("enabled", True),
    )
    r.set_required_flags(kwargs.get("required_flags", []))
    r.set_exclude_flags(kwargs.get("exclude_flags", []))
    db.add(r)
    db.flush()
    for grid_dict in kwargs.get("grids", []):
        create_grid(db, r.id, **grid_dict)
    return r


def get_regime(db: Session, regime_id: int) -> Optional[StrategyRegime]:
    return db.query(StrategyRegime).filter(StrategyRegime.id == regime_id).first()


def list_regimes(db: Session, strategy_id: int) -> List[StrategyRegime]:
    return (
        db.query(StrategyRegime)
        .filter(StrategyRegime.strategy_id == strategy_id)
        .order_by(StrategyRegime.priority.desc(), StrategyRegime.id)
        .all()
    )


def update_regime(db: Session, regime: StrategyRegime, **kwargs) -> StrategyRegime:
    for field in ("name", "priority", "base_volume", "clear_position", "enabled"):
        if field in kwargs:
            setattr(regime, field, kwargs[field])
    if "required_flags" in kwargs:
        regime.set_required_flags(kwargs["required_flags"])
    if "exclude_flags" in kwargs:
        regime.set_exclude_flags(kwargs["exclude_flags"])
    return regime


def delete_regime(db: Session, regime: StrategyRegime) -> None:
    db.delete(regime)
    db.flush()


# ─────────────── StrategyGrid CRUD ───────────────


def create_grid(db: Session, regime_id: int, **kwargs) -> StrategyGrid:
    g = StrategyGrid(
        regime_id=regime_id,
        direction=kwargs["direction"],
        step_offset=kwargs.get("step_offset", 0.0),
        trigger_price=kwargs.get("trigger_price", 0.0),
        volume=kwargs.get("volume", 0),
        max_fires=kwargs.get("max_fires"),
        enabled=kwargs.get("enabled", True),
        priority=kwargs.get("priority", 0),
    )
    db.add(g)
    db.flush()
    return g


def get_grid(db: Session, grid_id: int) -> Optional[StrategyGrid]:
    return db.query(StrategyGrid).filter(StrategyGrid.id == grid_id).first()


def list_grids(db: Session, regime_id: int) -> List[StrategyGrid]:
    return (
        db.query(StrategyGrid)
        .filter(StrategyGrid.regime_id == regime_id)
        .order_by(StrategyGrid.priority.desc(), StrategyGrid.id)
        .all()
    )


def update_grid(db: Session, grid: StrategyGrid, **kwargs) -> StrategyGrid:
    for field in ("direction", "step_offset", "trigger_price", "volume",
                  "max_fires", "fired_count", "enabled", "priority"):
        if field in kwargs:
            setattr(grid, field, kwargs[field])
    return grid


def delete_grid(db: Session, grid: StrategyGrid) -> None:
    db.delete(grid)
    db.flush()


def increment_fired_count(db: Session, grid: StrategyGrid) -> None:
    """网格触发后累加 fired_count（调用方 commit）"""
    grid.fired_count = (grid.fired_count or 0) + 1
    db.flush()


# ─────────────── StrategyAudit ───────────────


def write_audit(
    db: Session,
    strategy_id: int,
    trd_date: str,
    trigger_type: str,
    *,
    regime_id: Optional[int] = None,
    flags_active: Optional[list] = None,
    current_price: Optional[float] = None,
    position_vol: Optional[int] = None,
    base_volume: Optional[int] = None,
    action_payload: Optional[dict] = None,
    order_no: Optional[str] = None,
    reject_reason: Optional[str] = None,
) -> StrategyAudit:
    """写一行 audit（每次评估无论是否触发都调）

    commit 由 caller 控制（API 端点批量写 + 单 commit；engine 写一行一 commit）
    """
    a = StrategyAudit(
        strategy_id=strategy_id,
        regime_id=regime_id,
        trd_date=trd_date,
        trigger_type=trigger_type,
        current_price=current_price,
        position_vol=position_vol,
        base_volume=base_volume,
        order_no=order_no,
        reject_reason=reject_reason,
    )
    a.set_flags_active(flags_active or [])
    a.set_action_payload(action_payload)
    db.add(a)
    db.flush()
    return a


def list_audits(
    db: Session,
    strategy_id: int,
    trd_date: str,
    limit: int = 200,
) -> List[StrategyAudit]:
    return (
        db.query(StrategyAudit)
        .filter(StrategyAudit.strategy_id == strategy_id, StrategyAudit.trd_date == trd_date)
        .order_by(StrategyAudit.created_at.desc(), StrategyAudit.id.desc())
        .limit(limit)
        .all()
    )