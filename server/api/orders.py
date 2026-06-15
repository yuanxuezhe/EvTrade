"""
orders.py — v4 重构版

写路径：先 DB 后 RPC
  POST /place                  → INSERT status=48 → 调 ord_stk(remark=order_no) → 改 status=49/55
  DELETE /{id}                 → 调 RPC cancel_ord，不本地改 status（等 push）

读路径：纯 DB
  GET /                        → 委托列表（DB 查，按 trading_day 默认）
  GET /history?trading_day=    → 任意交易日历史
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel
from sqlalchemy import desc
import logging
import json

from db import get_db, SessionLocal
from models.orm import Order
from auth.deps import get_current_user
from models.user import User
from services.guards import require_trader, require_trading_day, require_trading_session
from services.order_no import next_order_no
from services.t0 import get_fee_config, calc_t0_volume, calc_net_amount
from rpc.client import ord_stk, cancel_order as rpc_cancel_order, qry_orders
from ws.manager import ws_manager

log = logging.getLogger(__name__)
router = APIRouter()


# ────────────── Pydantic ──────────────

class PlaceOrderRequest(BaseModel):
    client_order_id: Optional[str] = None
    stock_code: str
    order_type: str          # 23=买 24=卖
    price_type: int = 11     # 11=限价
    price: float
    volume: int
    t0_coefficient: float = 1.0


class OrderOut(BaseModel):
    order_id: str
    client_order_id: str
    order_no: str
    order_remark: str
    TRD_DATE: str
    stock_code: str
    order_type: str
    price_type: int
    price: float
    volume: int
    traded_volume: int
    traded_amount: float
    avg_price: float
    status: str
    status_msg: str
    order_time: str


class PlaceOrderResponse(BaseModel):
    code: int = 0
    msg: str = ""
    order: Optional[OrderOut] = None
    broker_order_id: str = ""
    fee_breakdown: Optional[dict] = None
    t0_adjusted_volume: Optional[int] = None
    error: Optional[str] = None


class ListOrdersResponse(BaseModel):
    code: int = 0
    msg: str = ""
    list: List[OrderOut] = []
    total: int = 0


class CancelResponse(BaseModel):
    code: int = 0
    msg: str = ""
    order_id: str
    cancel_ack: Optional[dict] = None
    error: Optional[str] = None


# ────────────── 写路径 ──────────────

@router.post("/place", response_model=PlaceOrderResponse,
             dependencies=[Depends(require_trader), Depends(require_trading_day), Depends(require_trading_session)])
async def place_order(req: PlaceOrderRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """下单（标准：先本地后柜台）"""
    if req.order_type not in ("23", "24"):
        raise HTTPException(status_code=400, detail={"code": "BAD_ORDER_TYPE", "msg": "order_type 必须 23(买) 24(卖)"})

    # 1. 取交易日内 client_order_id 幂等
    trd_date = db.query(__import__("models.orm", fromlist=["TradingDay"]).TradingDay)\
                 .filter_by(status='active').first().current_date
    cid = req.client_order_id or f"cid-{int(datetime.utcnow().timestamp() * 1000)}"
    existing = db.query(Order).filter_by(client_order_id=cid, TRD_DATE=trd_date).first()
    if existing:
        return PlaceOrderResponse(
            code=0, msg="幂等: 已存在",
            order=OrderOut(
                order_id=existing.order_id, client_order_id=existing.client_order_id,
                order_no=existing.order_no, order_remark=existing.order_remark,
                TRD_DATE=existing.TRD_DATE, stock_code=existing.stock_code,
                order_type=existing.order_type, price_type=existing.price_type,
                price=existing.price, volume=existing.volume,
                traded_volume=existing.traded_volume, traded_amount=existing.traded_amount,
                avg_price=existing.avg_price, status=existing.status,
                status_msg=existing.status_msg, order_time=existing.order_time,
            ),
        )

    # 2. T0 配平
    direction = "BUY" if req.order_type == "23" else "SELL"
    adjusted = calc_t0_volume(req.volume, req.t0_coefficient, direction)
    if adjusted <= 0:
        raise HTTPException(
            status_code=400,
            detail={"code": "VOLUME_TOO_SMALL", "msg": f"T0 配平后 0 股 (目标 {req.volume} × 系数 {req.t0_coefficient})"}
        )

    # 3. 算费
    fee_cfg = get_fee_config()
    gross, net = calc_net_amount(req.price, adjusted, fee_cfg, direction)

    # 4. INSERT status=48（待报）
    order_no = next_order_no(db)
    order_id = f"ORD-{order_no}"
    order = Order(
        order_id=order_id, client_order_id=cid, order_no=order_no, order_remark=order_no,
        TRD_DATE=trd_date,
        stock_code=req.stock_code, order_type=req.order_type,
        price_type=req.price_type, price=req.price, volume=adjusted,
        traded_volume=0, traded_amount=0.0, avg_price=0.0,
        status="48", status_msg="待报",
        order_time=datetime.utcnow().isoformat(timespec='seconds'),
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    # 5. 调 RPC
    try:
        ack = await ord_stk(
            stock_code=req.stock_code, order_type=req.order_type,
            price_type=req.price_type, price=req.price, volume=adjusted,
            remark=order_no,
        )
    except Exception as e:
        order.status = "55"
        order.status_msg = f"RPC 失败: {e}"
        db.commit()
        db.refresh(order)
        return PlaceOrderResponse(
            code=1, msg="柜台调用失败",
            order=OrderOut(
                order_id=order.order_id, client_order_id=order.client_order_id,
                order_no=order.order_no, order_remark=order.order_remark,
                TRD_DATE=order.TRD_DATE,
                stock_code=order.stock_code, order_type=order.order_type,
                price_type=order.price_type, price=order.price, volume=order.volume,
                traded_volume=order.traded_volume, traded_amount=order.traded_amount,
                avg_price=order.avg_price, status=order.status,
                status_msg=order.status_msg, order_time=order.order_time,
            ),
            error=str(e), t0_adjusted_volume=adjusted,
        )

    # 6. 解析 ack（成功 → 49；失败 → 55）
    ack_code = int(ack.get("code", -1))
    ack_list = ack.get("list", [])
    broker_order_id = ""
    if ack_code == 0 and ack_list and isinstance(ack_list[0], dict):
        broker_order_id = str(ack_list[0].get("order_id", ""))
        if broker_order_id:
            order.order_id = broker_order_id
        order.status = "49"
        order.status_msg = "已报"
    else:
        order.status = "55"
        order.status_msg = ack.get("msg", "柜台拒单")
    db.commit()
    db.refresh(order)

    # 7. 推 WS
    try:
        await ws_manager.broadcast("order_update", {
            "order_id": order.order_id,
            "stock_code": order.stock_code,
            "status": order.status,
            "volume": order.volume,
            "traded_volume": order.traded_volume,
        })
    except Exception as e:
        log.warning("WS push failed: %s", e)

    return PlaceOrderResponse(
        code=0 if order.status == "49" else 1,
        msg=order.status_msg,
        order=OrderOut(
            order_id=order.order_id, client_order_id=order.client_order_id,
            order_no=order.order_no, order_remark=order.order_remark,
            TRD_DATE=order.TRD_DATE, stock_code=order.stock_code,
            order_type=order.order_type, price_type=order.price_type,
            price=order.price, volume=order.volume,
            traded_volume=order.traded_volume, traded_amount=order.traded_amount,
            avg_price=order.avg_price, status=order.status,
            status_msg=order.status_msg, order_time=order.order_time,
        ),
        broker_order_id=broker_order_id,
        fee_breakdown={"gross": gross, "net": net, "commission_rate": fee_cfg.commission_rate},
        t0_adjusted_volume=adjusted,
    )


# ────────────── 撤单 ──────────────

@router.delete("/{order_id}", response_model=CancelResponse,
               dependencies=[Depends(require_trader), Depends(require_trading_day), Depends(require_trading_session)])
async def cancel_order(order_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """撤单：只调 RPC，不本地改 status（等 ord_cfm push）"""
    order = db.query(Order).filter_by(order_id=order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "msg": f"委托 {order_id} 不存在"})

    if order.status not in ("48", "49"):
        # 已报才能撤
        return CancelResponse(
            code=1, msg=f"当前 status={order.status} 不可撤",
            order_id=order_id, error=f"status {order.status} non-cancellable",
        )

    try:
        ack = await rpc_cancel_order(order_id=order_id)
        ack_code = int(ack.get("code", -1))
        if ack_code == 0:
            # 成功 → 等 push 改 status
            return CancelResponse(code=0, msg="撤单请求已发", order_id=order_id, cancel_ack=ack)
        else:
            return CancelResponse(
                code=1, msg=ack.get("msg", "撤单失败"), order_id=order_id,
                cancel_ack=ack, error=ack.get("msg", "cancel rejected"),
            )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={"code": "RPC_FAILED", "msg": f"撤单 RPC 失败: {e}",
                    "order_id": order_id, "error": str(e)},
        )


# ────────────── 读路径 ──────────────

@router.get("", response_model=ListOrdersResponse)
async def list_orders(
    stock_code: Optional[str] = None,
    status: Optional[str] = None,
    trading_day: Optional[str] = None,
    limit: int = Query(100, le=500),
    offset: int = 0,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """委托列表（纯 DB，按 trading_day 默认 = 激活日）"""
    if not trading_day:
        active = db.query(__import__("models.orm", fromlist=["TradingDay"]).TradingDay)\
                    .filter_by(status='active').first()
        trading_day = active.current_date if active else None

    q = db.query(Order).filter(Order.TRD_DATE == trading_day) if trading_day else db.query(Order)
    if stock_code:
        q = q.filter(Order.stock_code == stock_code)
    if status:
        q = q.filter(Order.status == status)
    total = q.count()
    rows = q.order_by(desc(Order.order_time)).offset(offset).limit(limit).all()

    return ListOrdersResponse(
        code=0, msg="", total=total,
        list=[
            OrderOut(
                order_id=r.order_id, client_order_id=r.client_order_id,
                order_no=r.order_no, order_remark=r.order_remark,
                TRD_DATE=r.TRD_DATE, stock_code=r.stock_code,
                order_type=r.order_type, price_type=r.price_type,
                price=r.price, volume=r.volume,
                traded_volume=r.traded_volume, traded_amount=r.traded_amount,
                avg_price=r.avg_price, status=r.status,
                status_msg=r.status_msg, order_time=r.order_time,
            ) for r in rows
        ],
    )


@router.get("/history", response_model=ListOrdersResponse)
async def orders_history(
    trading_day: str = Query(..., description="8 位数字 YYYYMMDD"),
    stock_code: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(500, le=2000),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """任意交易日历史委托（admin 也用）"""
    q = db.query(Order).filter(Order.TRD_DATE == trading_day)
    if stock_code:
        q = q.filter(Order.stock_code == stock_code)
    if status:
        q = q.filter(Order.status == status)
    total = q.count()
    rows = q.order_by(desc(Order.order_time)).limit(limit).all()
    return ListOrdersResponse(
        code=0, msg="", total=total,
        list=[
            OrderOut(
                order_id=r.order_id, client_order_id=r.client_order_id,
                order_no=r.order_no, order_remark=r.order_remark,
                TRD_DATE=r.TRD_DATE, stock_code=r.stock_code,
                order_type=r.order_type, price_type=r.price_type,
                price=r.price, volume=r.volume,
                traded_volume=r.traded_volume, traded_amount=r.traded_amount,
                avg_price=r.avg_price, status=r.status,
                status_msg=r.status_msg, order_time=r.order_time,
            ) for r in rows
        ],
    )
