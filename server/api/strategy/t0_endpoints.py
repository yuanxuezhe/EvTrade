"""
api/strategy/t0_endpoints.py — T0 策略 REST 端点

路由（注册到 /api/strategy/t0）：
  GET    /                              列表（type='t0'）
  POST   /                              创建 T0 策略
  GET    /{id}                          详情 + 参数
  PUT    /{id}                          更新参数（含 test_mode 热切换）
  DELETE /{id}                          删除
  POST   /{id}/control                  pause/resume/stop
  GET    /{id}/signals                  当日信号历史
  GET    /{id}/positions                当前 T0 敞口
"""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from server.config import settings
from server.db import get_db
from server.auth.deps import get_current_user
from server.models.user import User
from server.services.strategy import repository as repo
from server.services.strategy.models import Strategy
from server.services.strategy.t0.models import T0StrategyParams
from server.api.strategy.t0_schemas import (
    T0StrategyCreate, T0StrategyUpdate, T0StrategyOut,
    T0SignalRecord, T0PositionRecord, ControlRequest,
)

log = logging.getLogger(__name__)


def _require_engine_enabled():
    if not settings.STRATEGY_ENGINE_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "STRATEGY_ENGINE_DISABLED",
                    "msg": "策略引擎未启用（设置 STRATEGY_ENGINE_ENABLED=1）"},
        )


def _load_t0_strategy(db: Session, strategy_id: int, user: User) -> Strategy:
    """加载 + 鉴权 + type='t0' 校验"""
    s = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    if not s:
        raise HTTPException(status_code=404, detail={"code": "STRATEGY_NOT_FOUND"})
    if s.type != "t0":
        raise HTTPException(status_code=400, detail={"code": "NOT_T0_STRATEGY"})
    if user.role != "admin" and s.user_id != user.id:
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN"})
    return s


async def _qc_subscribe(strategy_id: int, stock_code: str) -> None:
    if not settings.STRATEGY_ENGINE_ENABLED:
        return
    try:
        from server.services.strategy.quote_consumer import get_quote_consumer
        qc = await get_quote_consumer()
        qc.subscribe_strategy(strategy_id, stock_code, strategy_type="t0")
    except Exception as e:
        log.warning("T0 qc subscribe failed: %s", e)


async def _qc_unsubscribe(strategy_id: int) -> None:
    if not settings.STRATEGY_ENGINE_ENABLED:
        return
    try:
        from server.services.strategy.quote_consumer import get_quote_consumer
        qc = await get_quote_consumer()
        qc.unsubscribe_strategy(strategy_id)
    except Exception as e:
        log.warning("T0 qc unsubscribe failed: %s", e)


def _build_t0_params(req: T0StrategyCreate) -> T0StrategyParams:
    """Pydantic schema → T0StrategyParams"""
    from server.services.strategy.t0.models import (
        T0VWAPParams, T0OpeningParams, T0BollingerParams, T0RiskParams,
    )
    return T0StrategyParams(
        test_mode=req.test_mode,
        models_enabled=req.models_enabled,
        signal_volume=req.signal_volume,
        signal_cooldown=req.signal_cooldown,
        vwap=T0VWAPParams(**req.vwap_params.dict()),
        opening=T0OpeningParams(**req.opening_params.dict()),
        bollinger=T0BollingerParams(**req.bollinger_params.dict()),
        risk=T0RiskParams(**req.risk_params.dict()),
    )


# ─────────────── Endpoints ───────────────

def register_t0_endpoints(router):
    prefix = "/t0"

    @router.get(f"{prefix}", response_model=List[T0StrategyOut])
    def list_t0_strategies(
        status_filter: Optional[str] = Query(None, alias="status"),
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        _require_engine_enabled()
        q = db.query(Strategy).filter(Strategy.type == "t0")
        if user.role != "admin":
            q = q.filter(Strategy.user_id == user.id)
        if status_filter:
            q = q.filter(Strategy.status == status_filter)
        return q.order_by(Strategy.updated_at.desc()).all()

    @router.post(f"{prefix}", response_model=T0StrategyOut, status_code=201)
    async def create_t0_strategy(
        req: T0StrategyCreate,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        _require_engine_enabled()
        t0_params = _build_t0_params(req)
        try:
            s = repo.create_strategy(
                db, user_id=user.id,
                stock_code=req.stock_code,
                type="t0",
                reference_price=req.reference_price,
                base_volume=req.base_volume,
                note=req.note,
                regimes=[],
            )
            repo.save_t0_params(db, s.id, t0_params)
            db.commit()
        except Exception as e:
            db.rollback()
            raise HTTPException(status_code=400, detail={"code": "CREATE_FAILED", "msg": str(e)})
        await _qc_subscribe(s.id, s.stock_code)
        return _load_t0_strategy(db, s.id, user)

    @router.get(f"{prefix}/{{strategy_id}}", response_model=T0StrategyOut)
    def get_t0_strategy(
        strategy_id: int,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        _require_engine_enabled()
        return _load_t0_strategy(db, strategy_id, user)

    @router.put(f"{prefix}/{{strategy_id}}", response_model=T0StrategyOut)
    async def update_t0_strategy(
        strategy_id: int,
        req: T0StrategyUpdate,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        _require_engine_enabled()
        s = _load_t0_strategy(db, strategy_id, user)

        # 更新基本信息
        update_data = req.dict(exclude_unset=True)
        for key in ("status", "base_volume", "note"):
            if key in update_data:
                setattr(s, key, update_data[key])

        # 更新 T0 参数
        existing = repo.get_t0_params(db, s.id)
        if "test_mode" in update_data:
            existing.test_mode = update_data["test_mode"]
        if "models_enabled" in update_data:
            existing.models_enabled = update_data["models_enabled"]
        if "signal_volume" in update_data:
            existing.signal_volume = update_data["signal_volume"]
        if "signal_cooldown" in update_data:
            existing.signal_cooldown = update_data["signal_cooldown"]
        if update_data.get("vwap_params"):
            vp = update_data["vwap_params"]
            for k, v in vp.dict().items():
                setattr(existing.vwap, k, v)
        if update_data.get("opening_params"):
            op = update_data["opening_params"]
            for k, v in op.dict().items():
                setattr(existing.opening, k, v)
        if update_data.get("bollinger_params"):
            bp = update_data["bollinger_params"]
            for k, v in bp.dict().items():
                setattr(existing.bollinger, k, v)
        if update_data.get("risk_params"):
            rp = update_data["risk_params"]
            for k, v in rp.dict().items():
                setattr(existing.risk, k, v)

        repo.save_t0_params(db, s.id, existing)
        db.commit()

        # 热更新 engine 参数
        if settings.STRATEGY_ENGINE_ENABLED:
            try:
                from server.services.strategy.quote_consumer import get_quote_consumer
                qc = await get_quote_consumer()
                t0_eng = qc._t0_engines.get(strategy_id)
                if t0_eng:
                    t0_eng.set_params(existing)
            except Exception as e:
                log.warning("T0 engine params update failed: %s", e)

        return _load_t0_strategy(db, strategy_id, user)

    @router.delete(f"{prefix}/{{strategy_id}}", status_code=204)
    async def delete_t0_strategy(
        strategy_id: int,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        _require_engine_enabled()
        s = _load_t0_strategy(db, strategy_id, user)
        await _qc_unsubscribe(s.id)
        repo.delete_strategy(db, s)
        db.commit()
        return None

    @router.post(f"{prefix}/{{strategy_id}}/control")
    async def control_t0_strategy(
        strategy_id: int,
        req: ControlRequest,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        _require_engine_enabled()
        s = _load_t0_strategy(db, strategy_id, user)
        if req.action not in ("pause", "resume", "stop"):
            raise HTTPException(status_code=400,
                                detail={"code": "INVALID_ACTION", "msg": f"不支持的动作: {req.action}"})
        status_map = {"pause": "paused", "resume": "active", "stop": "stopped"}
        repo.update_strategy(db, s, status=status_map[req.action])
        repo.write_audit(
            db, strategy_id=s.id,
            trd_date=datetime.now().strftime("%Y%m%d"),
            trigger_type=f"t0_control_{req.action}",
            action_payload={"action": req.action, "user_id": user.id},
        )
        if req.action == "resume":
            await _qc_subscribe(s.id, s.stock_code)
        elif req.action in ("pause", "stop"):
            await _qc_unsubscribe(s.id)
        db.commit()
        return {"ok": True, "action": req.action, "strategy_id": strategy_id, "status": s.status}

    @router.get(f"{prefix}/{{strategy_id}}/signals", response_model=List[T0SignalRecord])
    def get_t0_signals(
        strategy_id: int,
        trd_date: str = Query(..., description="8 位数字 YYYYMMDD"),
        limit: int = Query(100, ge=1, le=500),
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        _require_engine_enabled()
        _load_t0_strategy(db, strategy_id, user)
        audits = repo.list_audits(db, strategy_id, trd_date, limit=limit)
        signals = []
        for a in audits:
            payload = a.get_action_payload() or {}
            signals.append(T0SignalRecord(
                strategy_id=a.strategy_id,
                signal_type=a.trigger_type.replace("t0_", "", 1),
                model=payload.get("model", ""),
                direction=payload.get("direction", ""),
                price=a.current_price or 0.0,
                volume=payload.get("volume", 0),
                reason=payload.get("reason", ""),
                strength=payload.get("strength", 0.5),
                order_no=a.order_no,
                reject_reason=a.reject_reason,
                timestamp=a.created_at,
            ))
        return signals

    @router.get(f"{prefix}/{{strategy_id}}/positions", response_model=Dict[str, Any])
    def get_t0_positions(
        strategy_id: int,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        """查询 T0 策略的当前敞口（内存状态，非 DB）"""
        _require_engine_enabled()
        s = _load_t0_strategy(db, strategy_id, user)
        positions = []
        params_dict = None
        try:
            from server.services.strategy.quote_consumer import get_quote_consumer
            qc = get_quote_consumer()  # 不 await，直接取实例
            t0_eng = qc._t0_engines.get(strategy_id)
            if t0_eng:
                positions = t0_eng._position_tracker.to_dicts()
                params_dict = t0_eng._params.to_dict()
        except Exception:
            pass

        # 参数从 DB 读
        t0_params = repo.get_t0_params(db, s.id)
        if params_dict is None:
            params_dict = t0_params.to_dict()

        return {
            "strategy_id": s.id,
            "stock_code": s.stock_code,
            "test_mode": t0_params.test_mode,
            "operations_today": len(positions),
            "open_positions": positions,
        }
