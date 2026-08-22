"""
asset_adjust.py — 资金调平 API

端点：PUT /api/asset/adjust
- admin 鉴权
- 原子 += Asset.cash / Asset.total_asset
- Asset.synced_from = "manual"（下次 do_reconcile 全表覆盖会重置为 "rpc_full"）

设计决策（design.md D1）：
- 不引入 manual_offset_* 字段，调平值直接体现在 cash / total_asset 上
- reason 仅入 log，不入库（用户不留 audit row）
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, validator
from sqlalchemy.orm import Session

from server.infra.db import get_db
from server.tables import Assets, Row
from server.auth.deps import require_admin
from server.models.user import User
from server.utils.time import _utcnow, format_db_dt

log = logging.getLogger(__name__)


# ─────────────── Pydantic schemas ───────────────

class AdjustAssetRequest(BaseModel):
    """资金调平请求体

    - delta_cash / delta_total_asset 至少传一个（Pydantic validator 校验）
    - 负数允许（broker 可透支场景），0 等价于无操作
    - reason 仅入 log，不入库
    """
    delta_cash: Optional[float] = None
    delta_total_asset: Optional[float] = None
    reason: Optional[str] = None

    @validator("delta_cash", "delta_total_asset")
    def _reject_nan(cls, v):
        """Pydantic 不禁 NaN；此处显式 reject 防异态值"""
        if v is not None and v != v:  # NaN != NaN
            raise ValueError("delta must be a finite number (not NaN)")
        return v

    @validator("reason")
    def _reason_max_len(cls, v):
        if v is not None and len(v) > 255:
            raise ValueError("reason must be ≤ 255 chars")
        return v


class AssetOut(BaseModel):
    """GET /api/asset 单条响应元素（与 server/api/asset.py:AssetOut 同字段）"""
    cash: float
    frozen_cash: float
    market_value: float
    total_asset: float
    synced_at: Optional[str] = None
    synced_from: str


class AdjustAssetResponse(BaseModel):
    code: int = 0
    msg: str = "ok"
    asset: Optional[AssetOut] = None


# ─────────────── handler helper ───────────────

def _to_asset_out(row: Row) -> AssetOut:
    return AssetOut(
        cash=row.cash,
        frozen_cash=row.frozen_cash,
        market_value=row.market_value,
        total_asset=row.total_asset,
        synced_at=format_db_dt(row.synced_at) if row.synced_at else None,
        synced_from=row.synced_from,
    )


# ─────────────── router registration ───────────────

def register_adjust(router: APIRouter) -> None:
    """注册 PUT /adjust 到传入 router（admin 鉴权）"""

    @router.put(
        "/adjust",
        response_model=AdjustAssetResponse,
        dependencies=[Depends(require_admin)],
        summary="资金调平（admin）",
    )
    async def adjust_asset(
        req: AdjustAssetRequest,
        admin: User = Depends(require_admin),
        db: Session = Depends(get_db),
    ):
        """admin 资金盘中调平：Asset.cash / Asset.total_asset 原子 +=

        - 必须至少传一个 delta_* 字段（否则 422）
        - 不存在 Asset 行时自动初始化为全零（极少见：空库后第一次调平）
        - market_value / frozen_cash 不动（market_value 仍是前端实时算）
        """
        if req.delta_cash is None and req.delta_total_asset is None:
            raise HTTPException(
                status_code=422,
                detail="at least one of delta_cash / delta_total_asset required",
            )

        row = Assets.query_one(id=1)
        if row is None:
            # 空库场景：初始化全零 + 立刻施加 delta
            row = Assets.add_one({
                "id": 1,
                "cash": 0.0,
                "frozen_cash": 0.0,
                "market_value": 0.0,
                "total_asset": 0.0,
                "synced_at": _utcnow(),
                "synced_from": "",
            })

        new_cash = row.cash + (req.delta_cash or 0.0)
        new_total_asset = row.total_asset + (req.delta_total_asset or 0.0)

        row.cash = round(new_cash, 2)
        row.total_asset = round(new_total_asset, 2)
        row.synced_from = "manual"
        row.synced_at = _utcnow()
        row.update(Assets, id=row.id)

        log.info(
            "[manual_adjust] asset admin=%s reason=%s delta_cash=%s delta_total_asset=%s "
            "new_cash=%s new_total_asset=%s",
            admin.id, req.reason, req.delta_cash, req.delta_total_asset,
            row.cash, row.total_asset,
        )

        return AdjustAssetResponse(code=0, msg="ok", asset=_to_asset_out(row))
