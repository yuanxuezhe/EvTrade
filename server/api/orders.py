from fastapi import APIRouter, HTTPException
from typing import List, Optional
from pydantic import BaseModel
from services.trading import get_orders, add_order, update_order_status
from models.types import Order
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
async def list_orders(stock_code: Optional[str] = None):
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

@router.post("", response_model=OrderResponse)
async def create_order(order_data: OrderCreate):
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

@router.delete("/{order_id}")
async def cancel_order(order_id: str):
    update_order_status(order_id, "cancelled")
    return {"order_id": order_id, "status": "cancelled"}