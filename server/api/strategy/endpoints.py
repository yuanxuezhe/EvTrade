"""
strategy/endpoints.py — strategy REST 8 端点实现（change strategy_trade task 9）

路由（注册到 router 上）：
  GET    /                              list（按 user 隔离）
  POST   /                              create（含嵌套）
  GET    /{id}                          detail
  PUT    /{id}                          update
  DELETE /{id}                          cascade delete
  POST   /{id}/control                  action: pause / resume / stop / clear_now
  GET    /{id}/audit                    audit 查询
  GET    /flags/definitions             flag 注册表
"""
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from server.config import settings
from server.db import get_db
from server.auth.deps import get_current_user
from server.models.user import User
from server.services.strategy import repository as repo
from server.services.strategy.models import Strategy, StrategyRegime
from server.services.strategy.flags import get_flag_definitions
from server.api.strategy.schemas import (
    StrategyCreate, StrategyUpdate, StrategyOut, ControlRequest,
    AuditRecord, FlagDefinition, FlagDefinitionsResponse,
)

log = logging.getLogger(__name__)


def _require_engine_enabled():
    """未启用 → 503"""
    if not settings.STRATEGY_ENGINE_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "STRATEGY_ENGINE_DISABLED",
                    "msg": "策略引擎未启用（设置 STRATEGY_ENGINE_ENABLED=1）"},
        )


def _load_strategy_owned(db: Session, strategy_id: int, user: User) -> Strategy:
    """加载 + 嵌套 eager-load + 鉴权"""
    s = (
        db.query(Strategy)
        .options(joinedload(Strategy.regimes).joinedload(StrategyRegime.grids))
        .filter(Strategy.id == strategy_id)
        .first()
    )
    if not s:
        raise HTTPException(status_code=404, detail={"code": "STRATEGY_NOT_FOUND"})
    if user.role != "admin" and s.user_id != user.id:
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN"})
    return s


async def _qc_subscribe(strategy_id: int, stock_code: str) -> None:
    """best-effort subscribe to quote_consumer（仅 STRATEGY_ENGINE_ENABLED）"""
    if not settings.STRATEGY_ENGINE_ENABLED:
        return
    try:
        from server.services.strategy.quote_consumer import get_quote_consumer
        qc = await get_quote_consumer()
        qc.subscribe_strategy(strategy_id, stock_code)
    except Exception as e:
        log.warning("qc subscribe failed: %s", e)


async def _qc_unsubscribe(strategy_id: int) -> None:
    """best-effort unsubscribe"""
    if not settings.STRATEGY_ENGINE_ENABLED:
        return
    try:
        from server.services.strategy.quote_consumer import get_quote_consumer
        qc = await get_quote_consumer()
        qc.unsubscribe_strategy(strategy_id)
    except Exception as e:
        log.warning("qc unsubscribe failed: %s", e)


# ─────────────── Endpoints（注册到 router）───────────────


def register_endpoints(router):
    @router.get("", response_model=List[StrategyOut])
    def list_strategies_endpoint(
        status_filter: Optional[str] = Query(None, alias="status"),
        type_filter: Optional[str] = Query(None, alias="type"),
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        _require_engine_enabled()
        if user.role == "admin":
            q = db.query(Strategy)
            if status_filter:
                q = q.filter(Strategy.status == status_filter)
            if type_filter:
                q = q.filter(Strategy.type == type_filter)
            return q.order_by(Strategy.updated_at.desc()).all()
        return repo.list_strategies(db, user_id=user.id, status=status_filter, type_=type_filter)

    @router.post("", response_model=StrategyOut, status_code=201)
    async def create_strategy_endpoint(
        req: StrategyCreate,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        _require_engine_enabled()
        try:
            s = repo.create_strategy(
                db, user_id=user.id, stock_code=req.stock_code,
                type=req.type, reference_price=req.reference_price,
                base_volume=req.base_volume, note=req.note,
                regimes=[r.dict() for r in req.regimes],
            )
            db.commit()
        except Exception as e:
            db.rollback()
            raise HTTPException(status_code=400, detail={"code": "CREATE_FAILED", "msg": str(e)})
        await _qc_subscribe(s.id, s.stock_code)
        return _load_strategy_owned(db, s.id, user)

    @router.get("/{strategy_id}", response_model=StrategyOut)
    def get_strategy_endpoint(
        strategy_id: int,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        _require_engine_enabled()
        return _load_strategy_owned(db, strategy_id, user)

    @router.put("/{strategy_id}", response_model=StrategyOut)
    def update_strategy_endpoint(
        strategy_id: int,
        req: StrategyUpdate,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        _require_engine_enabled()
        s = _load_strategy_owned(db, strategy_id, user)
        repo.update_strategy(db, s, **req.dict(exclude_unset=True))
        db.commit()
        return _load_strategy_owned(db, strategy_id, user)

    @router.delete("/{strategy_id}", status_code=204)
    async def delete_strategy_endpoint(
        strategy_id: int,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        _require_engine_enabled()
        s = _load_strategy_owned(db, strategy_id, user)
        await _qc_unsubscribe(s.id)
        repo.delete_strategy(db, s)
        db.commit()
        return None

    @router.post("/{strategy_id}/control")
    async def control_strategy_endpoint(
        strategy_id: int,
        req: ControlRequest,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        _require_engine_enabled()
        s = _load_strategy_owned(db, strategy_id, user)
        action = req.action
        if action not in ("pause", "resume", "stop", "clear_now"):
            raise HTTPException(
                status_code=400,
                detail={"code": "INVALID_ACTION", "msg": f"不支持的动作: {action}"},
            )
        status_map = {"pause": "paused", "resume": "active", "stop": "stopped"}
        if action in status_map:
            repo.update_strategy(db, s, status=status_map[action])
        repo.write_audit(
            db, strategy_id=s.id,
            trd_date=datetime.now().strftime("%Y%m%d"),
            trigger_type=f"control_{action}",
            action_payload={"action": action, "user_id": user.id},
        )
        # sync quote_consumer
        if action == "resume":
            await _qc_subscribe(s.id, s.stock_code)
        elif action in ("pause", "stop"):
            await _qc_unsubscribe(s.id)
        db.commit()
        return {"ok": True, "action": action, "strategy_id": strategy_id, "status": s.status}

    @router.get("/{strategy_id}/audit", response_model=List[AuditRecord])
    def get_audit_endpoint(
        strategy_id: int,
        trd_date: str = Query(..., description="8 位数字 YYYYMMDD"),
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        _require_engine_enabled()
        _load_strategy_owned(db, strategy_id, user)  # 鉴权
        return repo.list_audits(db, strategy_id, trd_date)

    @router.get("/flags/definitions", response_model=FlagDefinitionsResponse)
    def get_flag_definitions_endpoint(
        user: User = Depends(get_current_user),
    ):
        """前端下拉数据源：无需灰度门（静态注册表）"""
        return FlagDefinitionsResponse(list=[
            FlagDefinition(**d) for d in get_flag_definitions()
        ])
