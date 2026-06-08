from fastapi import APIRouter
from typing import List, Optional
from pydantic import BaseModel
from services.trading import get_trades

router = APIRouter()

class TradeResponse(BaseModel):
    trade_id: str
    order_id: str
    stock_code: str
    direction: str
    volume: int
    price: float
    trade_time: str

@router.get("", response_model=List[TradeResponse])
async def list_trades(stock_code: Optional[str] = None):
    trades = get_trades(stock_code)
    return [
        TradeResponse(
            trade_id=t.trade_id,
            order_id=t.order_id,
            stock_code=t.stock_code,
            direction=t.direction,
            volume=t.volume,
            price=t.price,
            trade_time=t.trade_time
        )
        for t in trades
    ]