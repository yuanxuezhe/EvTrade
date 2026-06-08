from fastapi import APIRouter
from typing import List
from pydantic import BaseModel
from services.trading import get_positions, init_position, get_position

router = APIRouter()

class PositionResponse(BaseModel):
    stock_code: str
    stock_name: str
    initial_position: int
    today_buy: int
    today_sell: int
    available: int
    total: int

@router.get("", response_model=List[PositionResponse])
async def list_positions():
    positions = get_positions()
    return [
        PositionResponse(
            stock_code=p.stock_code,
            stock_name=p.stock_name,
            initial_position=p.initial_position,
            today_buy=p.today_buy,
            today_sell=p.today_sell,
            available=p.available,
            total=p.total
        )
        for p in positions
    ]

@router.post("/{stock_code}/init", response_model=PositionResponse)
async def init_stock_position(stock_code: str):
    pos = init_position(stock_code)
    if not pos:
        return {"error": "position not found"}
    return PositionResponse(
        stock_code=pos.stock_code,
        stock_name=pos.stock_name,
        initial_position=pos.initial_position,
        today_buy=pos.today_buy,
        today_sell=pos.today_sell,
        available=pos.available,
        total=pos.total
    )