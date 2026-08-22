"""
position_adjust.py — 持仓调平 API

端点：PUT /api/positions/{stock_code}/adjust
- admin 鉴权
- 原子 += Position.vol / Position.avl_vol
- Position.synced_from = "manual"（下次 do_reconcile 全表覆盖会重置为 "rpc_full"）

设计决策（design.md D1）：
- 不引入 manual_offset_* 字段，调平值直接体现在 vol / avl_vol 上
- stock_code 由 URL path 定位，未找到的 Position 返 404（不自动新建防误操作）
- cost_price / last_vol 不动（仅 do_reconcile 写）
- reason 仅入 log，不入库
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, validator

from server.infra.db import get_db
from server.tables import Positions, Row
from server.auth.deps import require_admin
from server.models.user import User
from server.utils.time import _utcnow, format_db_dt

log = logging.getLogger(__name__)

# 错误码常量（与 spec 一致）
POSITION_NOT_FOUND = "POSITION_NOT_FOUND"


# ─────────────── Pydantic schemas ───────────────

class AdjustPositionRequest(BaseModel):
    """持仓调平请求体

    - delta_vol / delta_avl_vol 至少传一个
    - 负数允许（broker 可用 > 总量是异常态但 UI 不限制；admin 自负其责）
    - 0 等价于无操作
    """
    delta_vol: Optional[int] = None
    delta_avl_vol: Optional[int] = None
    reason: Optional[str] = None

    @validator("reason")
    def _reason_max_len(cls, v):
        if v is not None and len(v) > 255:
            raise ValueError("reason must be ≤ 255 chars")
        return v


class PositionOut(BaseModel):
    """与 server/api/positions.py:PositionOut 同字段"""
    stock_code: str
    stock_name: str
    last_vol: int
    avl_vol: int
    vol: int
    cost_price: float
    market_value: float
    synced_at: Optional[str] = None
    synced_from: str


class AdjustPositionResponse(BaseModel):
    code: int = 0
    msg: str = "ok"
    position: Optional[PositionOut] = None


# ─────────────── handler helper ───────────────

def _to_position_out(r: Row) -> PositionOut:
    return PositionOut(
        stock_code=r.stock_code,
        stock_name=r.stock_name,
        last_vol=r.last_vol,
        avl_vol=r.avl_vol,
        vol=r.vol,
        cost_price=r.cost_price,
        # 成本市值代理：cost_price * vol（前端行情到位后由 liveMarketValue 覆盖）
        market_value=round(r.cost_price * r.vol, 2),
        synced_at=format_db_dt(r.synced_at) if r.synced_at else None,
        synced_from=r.synced_from,
    )


# ─────────────── router registration ───────────────

def register_adjust(router: APIRouter) -> None:
    """注册 PUT /{stock_code}/adjust 到传入 router（admin 鉴权）"""

    @router.put(
        "/{stock_code}/adjust",
        response_model=AdjustPositionResponse,
        dependencies=[Depends(require_admin)],
        summary="持仓调平（admin）",
    )
    async def adjust_position(
        stock_code: str = Path(..., description="股票代码（PK）"),
        req: AdjustPositionRequest = ...,
        admin: User = Depends(require_admin),
        ):
        """admin 持仓盘中调平：Position.vol / Position.avl_vol 原子 +=

        - 必须至少传一个 delta_* 字段（否则 422）
        - 未找到 Position 行返 404（不自动新建）
        - 同时传 delta_vol + delta_avl_vol 时两个都动；只传其一则另一个不动
        """
        if req.delta_vol is None and req.delta_avl_vol is None:
            raise HTTPException(
                status_code=422,
                detail="at least one of delta_vol / delta_avl_vol required",
            )

        row = Positions.query_one(stock_code=stock_code)
        if row is None:
            raise HTTPException(
                status_code=404,
                detail=f"{POSITION_NOT_FOUND}: no Position for stock_code={stock_code}",
            )

        if req.delta_vol is not None:
            row.vol = row.vol + int(req.delta_vol)
        if req.delta_avl_vol is not None:
            row.avl_vol = row.avl_vol + int(req.delta_avl_vol)
        row.synced_from = "manual"
        row.synced_at = _utcnow()
        row.update(Positions, stock_code=row.stock_code)

        log.info(
            "[manual_adjust] position admin=%s stock_code=%s reason=%s "
            "delta_vol=%s delta_avl_vol=%s new_vol=%s new_avl_vol=%s",
            admin.id, stock_code, req.reason,
            req.delta_vol, req.delta_avl_vol,
            row.vol, row.avl_vol,
        )

        return AdjustPositionResponse(code=0, msg="ok", position=_to_position_out(row))
