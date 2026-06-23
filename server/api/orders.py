"""
orders.py — v6 重构版（order_no 作 PK, status 本地推断）

写路径：先 DB 后 RPC
  POST /place                  → INSERT status=48 (order_id 空) → 调 ord_stk(remark=order_no)
                                  → broker 带回 order_id 时 UPDATE 写入
                                  → ord_cfm 到达时由 _infer_order_status 推断 status
  DELETE /{order_no}           → 查 Order by (trd_date, order_no) → 内部用 order.order_id
                                  调 RPC cancel_ord；order_id 未到达时返 409 BROKER_NOT_READY
                                  → 不本地改 status（等 push）

读路径：纯 DB
  GET /                        → 委托列表（DB 查，按 trd_date 默认）
  GET /history?trd_date=       → 任意交易日历史

v6 改动（order-pk-by-orderno change）：
- 复合主键 (trd_date, order_no) — order_no 是 PK
- order_id 改成 nullable,broker 推送到达时单条 UPDATE 写入
- 删 PENDING-{order_no} 占位 + 删-插交换
- 撤单 URL 参数从 order_id 改为 order_no
- OrderOut.order_id 默认空串 (broker 未回报前)
- 撤单时 broker order_id 尚未到达返 409 BROKER_NOT_READY
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime, timezone
from pydantic import BaseModel
from sqlalchemy import desc
import logging
import json

from server.db import get_db, SessionLocal
from server.models.orm import Order, SysStatus
from server.auth.deps import get_current_user
from server.models.user import User
from server.services.guards import require_trader, require_trading_day, require_trading_session
from server.services.order_no import next_order_no
from server.services.t0 import get_fee_config, calc_t0_volume, calc_net_amount
from server.rpc.client import ord_stk, cancel_order as rpc_cancel_order, qry_orders
from server.ws.manager import ws_manager
from server.constants import PriceType, OrderType

log = logging.getLogger(__name__)
router = APIRouter()


# ────────────── Pydantic ──────────────

class PlaceOrderRequest(BaseModel):
    user_def: str = ""                # 外部自定义信息透传（无业务约束）
    stock_code: str
    order_type: str          # 23=买 24=卖
    price_type: int = PriceType.LIMIT  # 默认限价单
    price: float
    volume: int
    t0_coefficient: float = 1.0


class OrderOut(BaseModel):
    order_id: str = ""  # 改:broker 未回报前为空串 (下单后 → ord_cfm 到达前的窗口期)
    user_def: str = ""  # v7:外部自定义信息透传（替代原 client_order_id）
    order_no: str
    trd_date: str
    stock_code: str
    order_type: str
    price_type: int
    price: float
    volume: int
    traded_volume: int
    traded_amount: float
    avg_price: float
    cancelled_volume: int = 0  # v8:累计撤单量（broker ord_cfm 累加）
    order_flag: int = 0  # v9:0=normal 1=cancel-order (本地代理撤单委托行)
    status: str
    status_msg: str
    order_time: str


class PlaceOrderResponse(BaseModel):
    code: int = 0
    msg: str = ""
    order: Optional[OrderOut] = None
    # v8: 统一 RPC 格式 list 字段（冗余 1 行，跟 GET /orders list 风格一致）
    #   - 前端 axios 拦截器解包后 res.data = list[0] = OrderOut
    #   - 保留 order 字段以兼容老代码
    list: List[OrderOut] = []
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
    # v9: 本地代理的「撤单委托」行（pre-check 失败时为 None;成功/失败时含 status=53/55）
    cancel_order: Optional[OrderOut] = None
    error: Optional[str] = None


# v8 增:Order → OrderOut 转换（消除 3 处重复；list 包装由调用方做）
def _to_order_out(o: "Order") -> OrderOut:
    return OrderOut(
        order_id=o.order_id or "", user_def=o.user_def,
        order_no=o.order_no, trd_date=o.trd_date, stock_code=o.stock_code,
        order_type=o.order_type, price_type=o.price_type,
        price=o.price, volume=o.volume,
        traded_volume=o.traded_volume, traded_amount=o.traded_amount,
        avg_price=o.avg_price, cancelled_volume=o.cancelled_volume or 0,
        order_flag=o.order_flag or 0,
        status=o.status,
        status_msg=o.status_msg, order_time=o.order_time,
    )


# ────────────── 写路径 ──────────────

@router.post("/place", response_model=PlaceOrderResponse,
             dependencies=[Depends(require_trader), Depends(require_trading_day), Depends(require_trading_session)])
async def place_order(req: PlaceOrderRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """下单（标准：先本地后柜台）"""
    if req.order_type not in ("23", "24"):
        raise HTTPException(status_code=400, detail={"code": "BAD_ORDER_TYPE", "msg": "order_type 必须 23(买) 24(卖)"})

    # 1. 取交易日 + order_no（v7：幂等改由 order_no 单调递增保证）
    trd_date = db.query(SysStatus).filter_by(status='active').first().trd_date

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
    # v6: order_id 不预占,broker 回报时单条 UPDATE 写入
    # v7: 删 client_order_id 字段 + uq_orders_client_trd 约束;加 user_def 透传
    order_no = next_order_no(db)
    order = Order(
        trd_date=trd_date,
        order_no=order_no,
        user_def=req.user_def,
        stock_code=req.stock_code, order_type=req.order_type,
        price_type=req.price_type, price=req.price, volume=adjusted,
        traded_volume=0, traded_amount=0.0, avg_price=0.0,
        status="48", status_msg="待报",
        order_time=datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec='seconds'),
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
        # v7 改: 加 log.exception 便于运维定位柜台故障
        log.exception("place_order RPC failed: stock=%s order_no=%s", req.stock_code, order_no)
        order.status = "55"
        order.status_msg = f"RPC 失败: {e}"
        db.commit()
        db.refresh(order)
        return PlaceOrderResponse(
            code=1, msg="柜台调用失败",
            order=_to_order_out(order),
            list=[_to_order_out(order)],
            error=str(e), t0_adjusted_volume=adjusted,
        )

    # 6. 解析 ack（成功 → 49；失败 → 55）
    ack_code = int(ack.get("code", -1))
    ack_list = ack.get("list", [])
    broker_order_id = ""
    if ack_code == 0 and ack_list and isinstance(ack_list[0], dict):
        broker_order_id = str(ack_list[0].get("order_id", ""))
        if broker_order_id:
            # v6: 单条 UPDATE 写入 broker 真实 order_id (不再删-插交换)
            order.order_id = broker_order_id
        # status 由 _infer_order_status 推断更准;但 ack 成功就先写 49,ord_cfm 来了会重算
        order.status = "49"
        order.status_msg = "已报"
    else:
        order.status = "55"
        order.status_msg = ack.get("msg", "柜台拒单")
    db.commit()
    db.refresh(order)

    # 7. 推 WS
    # v8 增: payload 加 trd_date + order_no + remark,前端 holdings 推送守门用
    #   - trd_date: 跟 OrderOut 字段保持一致,前端做激活日守门
    #   - order_no: 本地 PK,前端推送匹配缓存用(等同 broker.remark)
    #   - remark:   broker 透传字段(等同 order_no),兼容 ws.js 旧逻辑
    try:
        await ws_manager.broadcast("order_update", {
            "trd_date": order.trd_date,
            "order_no": order.order_no,
            "remark": order.order_no,  # 冗余:等 broker 推回来时能 match
            "order_id": order.order_id or "",
            "stock_code": order.stock_code,
            "status": order.status,
            "status_msg": order.status_msg,
            "volume": order.volume,
            "traded_volume": order.traded_volume,
        })
    except Exception as e:
        log.warning("WS push failed: %s", e)

    return PlaceOrderResponse(
        code=0 if order.status == "49" else 1,
        msg=order.status_msg,
        order=_to_order_out(order),
        list=[_to_order_out(order)],
        broker_order_id=broker_order_id,
        fee_breakdown={"gross": gross, "net": net, "commission_rate": fee_cfg.commission_rate},
        t0_adjusted_volume=adjusted,
    )


# ────────────── 撤单 ──────────────

@router.delete("/{order_no}", response_model=CancelResponse,
               dependencies=[Depends(require_trader), Depends(require_trading_day), Depends(require_trading_session)])
async def cancel_order(order_no: str, trd_date: str = Query(..., description="8 位数字 YYYYMMDD"),
                      user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """撤单：只调 RPC，不本地改 status（等 ord_cfm push）

    v6: URL 参数改为 order_no (本地 8 位序号),内部用查到的 order.order_id 调 RPC
    """
    order = db.query(Order).filter_by(order_no=order_no, trd_date=trd_date).first()
    if not order:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "msg": f"委托 {order_no} 不存在"})

    if order.status not in ("48", "49"):
        # 已报才能撤
        return CancelResponse(
            code=1, msg=f"当前 status={order.status} 不可撤",
            order_id=order.order_id or "", error=f"status {order.status} non-cancellable",
        )

    if not order.order_id:
        # v6 防御:broker 尚未回报真实 order_id,不能调 cancel_ord
        return CancelResponse(
            code=1, msg="broker 尚未回报 order_id,暂不可撤",
            order_id="", error="BROKER_NOT_READY",
        )

    try:
        ack = await rpc_cancel_order(order_id=order.order_id)
        ack_code = int(ack.get("code", -1))
        if ack_code == 0:
            # 成功 → 等 push 改 status
            return CancelResponse(code=0, msg="撤单请求已发", order_id=order.order_id, cancel_ack=ack)
        else:
            return CancelResponse(
                code=1, msg=ack.get("msg", "撤单失败"), order_id=order.order_id,
                cancel_ack=ack, error=ack.get("msg", "cancel rejected"),
            )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={"code": "RPC_FAILED", "msg": f"撤单 RPC 失败: {e}",
                    "order_no": order_no, "order_id": order.order_id, "error": str(e)},
        )


# ────────────── 读路径 ──────────────

@router.get("", response_model=ListOrdersResponse)
async def list_orders(
    stock_code: Optional[str] = None,
    status: Optional[str] = None,
    trd_date: Optional[str] = Query(None, description="8 位数字 YYYYMMDD，缺省 = 激活日"),
    limit: int = Query(100, le=500),
    offset: int = 0,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """委托列表（纯 DB，按 trd_date 默认 = 激活日）"""
    if not trd_date:
        active = db.query(SysStatus).filter_by(status='active').first()
        trd_date = active.trd_date if active else None

    q = db.query(Order).filter(Order.trd_date == trd_date) if trd_date else db.query(Order)
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
                order_id=r.order_id or "", user_def=r.user_def,
                order_no=r.order_no, trd_date=r.trd_date, stock_code=r.stock_code,
                order_type=r.order_type, price_type=r.price_type,
                price=r.price, volume=r.volume,
                traded_volume=r.traded_volume, traded_amount=r.traded_amount,
                avg_price=r.avg_price, order_flag=r.order_flag or 0,
                status=r.status,
                status_msg=r.status_msg, order_time=r.order_time,
            ) for r in rows
        ],
    )


@router.get("/history", response_model=ListOrdersResponse)
async def orders_history(
    trd_date: str = Query(..., description="8 位数字 YYYYMMDD"),
    stock_code: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(500, le=2000),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """任意交易日历史委托（admin 也用）"""
    q = db.query(Order).filter(Order.trd_date == trd_date)
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
                order_id=r.order_id or "", user_def=r.user_def,
                order_no=r.order_no, trd_date=r.trd_date, stock_code=r.stock_code,
                order_type=r.order_type, price_type=r.price_type,
                price=r.price, volume=r.volume,
                traded_volume=r.traded_volume, traded_amount=r.traded_amount,
                avg_price=r.avg_price, order_flag=r.order_flag or 0,
                status=r.status,
                status_msg=r.status_msg, order_time=r.order_time,
            ) for r in rows
        ],
    )
