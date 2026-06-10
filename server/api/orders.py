from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional
from pydantic import BaseModel
from services.trading import get_orders, add_order, update_order_status
from models.types import Order
from rpc.client import qry_orders, ord_stk
from auth.deps import require_trader
import uuid
from datetime import datetime

router = APIRouter()

class OrderCreate(BaseModel):
    stock_code: str
    direction: str
    volume: int
    price: float
    price_type: str = "LIMIT"

class OrderResponse(BaseModel):
    order_id: str
    stock_code: str
    direction: str
    volume: int
    price: float
    price_type: str
    status: str
    traded_volume: int
    traded_price: float
    order_time: str

@router.get("", response_model=List[OrderResponse])
async def list_orders(stock_code: Optional[str] = None, use_rpc: bool = True):
    if use_rpc:
        try:
            orders = await qry_orders()
            return [
                OrderResponse(
                    order_id=o["order_id"],
                    stock_code=o["stock_code"],
                    direction=o.get("direction", "BUY"),
                    volume=o["volume"],
                    price=o["price"],
                    price_type=o.get("order_type", "LIMIT"),
                    status=_map_status(o["status"]),
                    traded_volume=o.get("traded_volume", 0),
                    traded_price=o.get("traded_price", 0.0),
                    order_time=o.get("order_time", "")
                )
                for o in orders
                if not stock_code or o["stock_code"] == stock_code
            ]
        except Exception as e:
            print(f"qry_orders error: {e}")
            return []

    orders = get_orders(stock_code)
    return [
        OrderResponse(
            order_id=o.order_id,
            stock_code=o.stock_code,
            direction=o.direction,
            volume=o.volume,
            price=o.price,
            price_type=o.price_type,
            status=o.status,
            traded_volume=o.traded_volume,
            traded_price=o.traded_price,
            order_time=o.order_time
        )
        for o in orders
    ]

def _map_status(status: str) -> str:
    """映射XtQuant状态码到前端状态键。

    完整 11 个状态（按 xtconstant 枚举）：
      48  ORDER_UNREPORTED       未报
      49  ORDER_WAIT_REPORTING   待报
      50  ORDER_REPORTED         已报
      51  ORDER_REPORTED_CANCEL  已报待撤
      52  ORDER_PARTSUCC_CANCEL  部成待撤
      53  ORDER_PART_CANCEL      部撤
      54  ORDER_CANCELED         已撤
      55  ORDER_PART_SUCC        部成
      56  ORDER_SUCCEEDED        已成
      57  ORDER_JUNK             废单
     255  ORDER_UNKNOWN          未知
    """
    status_map = {
        "48":  "unreported",
        "49":  "pending_report",
        "50":  "reported",
        "51":  "reported_cancel",
        "52":  "partial_pending_cancel",
        "53":  "partial_cancelled",
        "54":  "cancelled",
        "55":  "partial",
        "56":  "filled",
        "57":  "rejected",
        "255": "unknown",
    }
    return status_map.get(str(status), "unknown")

@router.post("", response_model=OrderResponse)
async def create_order(order_data: OrderCreate, _=Depends(require_trader)):
    order = Order(
        order_id=str(uuid.uuid4())[:8],
        stock_code=order_data.stock_code,
        direction=order_data.direction,
        volume=order_data.volume,
        price=order_data.price,
        price_type=order_data.price_type,
        status="pending",
        order_time=datetime.now().strftime("%H:%M:%S")
    )
    add_order(order)
    return OrderResponse(
        order_id=order.order_id,
        stock_code=order.stock_code,
        direction=order.direction,
        volume=order.volume,
        price=order.price,
        price_type=order.price_type,
        status=order.status,
        traded_volume=order.traded_volume,
        traded_price=order.traded_price,
        order_time=order.order_time
    )

@router.post("/place", response_model=OrderResponse)
async def place_order(order_data: OrderCreate, _=Depends(require_trader)):
    """通过RPC下单 ord_stk"""
    try:
        result = await ord_stk(
            stock_code=order_data.stock_code,
            volume=order_data.volume,
            price_type=order_data.price_type,
            price=order_data.price,
            direction=order_data.direction
        )
        return OrderResponse(
            order_id=result.get("order_id", ""),
            stock_code=order_data.stock_code,
            direction=order_data.direction,
            volume=order_data.volume,
            price=order_data.price,
            price_type=order_data.price_type,
            status=result.get("status", "pending"),
            traded_volume=0,
            traded_price=0.0,
            order_time=datetime.now().strftime("%H:%M:%S")
        )
    except Exception as e:
        print(f"ord_stk error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{order_id}")
async def cancel_order(order_id: str, _=Depends(require_trader)):
    update_order_status(order_id, "cancelled")
    return {"order_id": order_id, "status": "cancelled"}