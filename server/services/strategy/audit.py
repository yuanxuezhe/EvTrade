"""
strategy — 触发审计写入（change strategy_trade task 6）

📖 详细 spec：openspec/changes/strategy_trade/specs/strategy/spec.md REQ-STRAT-006 §8
📌 每次评估无论触发与否写一行 audit（含 no_action / no_match）
📌 wrapper 简化调用：自动 commit + 默认 trd_date 当日
📌 trigger_type 取值见 models.py StrategyAudit.__doc__
"""
from typing import Optional

from sqlalchemy.orm import Session

from server.services.strategy.models import StrategyAudit
from server.services.strategy import repository as repo


def write_audit(
    db: Session,
    strategy_id: int,
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
    trd_date: Optional[str] = None,
) -> StrategyAudit:
    """写一行 audit + commit

    📌 trd_date=None 时用当日（spec 格式 YYYYMMDD，由 caller 显式传或后续改成 DB 取 SysStatus）
    📌 commit 在 wrapper 内一次完成（engine 不需要再管事务）
    """
    if trd_date is None:
        # 当日 YYYYMMDD（避免依赖 DB SysStatus；engine 已在调用前获取过 trd_date）
        from datetime import datetime
        trd_date = datetime.now().strftime("%Y%m%d")
    a = repo.write_audit(
        db,
        strategy_id=strategy_id,
        trd_date=trd_date,
        trigger_type=trigger_type,
        regime_id=regime_id,
        flags_active=flags_active,
        current_price=current_price,
        position_vol=position_vol,
        base_volume=base_volume,
        action_payload=action_payload,
        order_no=order_no,
        reject_reason=reject_reason,
    )
    db.commit()
    db.refresh(a)
    return a


__all__ = ["write_audit"]