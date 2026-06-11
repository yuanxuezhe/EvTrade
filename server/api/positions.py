from fastapi import APIRouter, Depends
from typing import List
from pydantic import BaseModel
from rpc.client import qry_positions
from services.trading import init_position
from auth.deps import require_trader

router = APIRouter()

class PositionResponse(BaseModel):
    stock_code: str
    stock_name: str
    initial_position: int
    today_buy: int
    today_sell: int
    available: int
    total: int


class PositionRpcResponse(BaseModel):
    code: int
    msg: str
    list: List[PositionResponse]


def _row_to_position(p: dict) -> PositionResponse:
    return PositionResponse(
        stock_code=p.get("stock_code", ""),
        stock_name=p.get("stock_name", ""),
        initial_position=p.get("initial_position", 0),
        today_buy=p.get("today_buy", 0),
        today_sell=p.get("today_sell", 0),
        available=p.get("available", 0),
        total=p.get("total", p.get("volume", 0)),
    )


@router.get("", response_model=PositionRpcResponse)
async def list_positions():
    try:
        data = await qry_positions()
        code = int(data.get("code", -1))
        msg = str(data.get("msg", ""))
        items = []
        if code == 0:
            items = [_row_to_position(p) for p in data.get("list", [])]
        return PositionRpcResponse(code=code, msg=msg, list=items)
    except Exception as e:
        print(f"qry_positions error: {e}")
        return PositionRpcResponse(code=-1, msg=str(e), list=[])


@router.post("/{stock_code}/init", response_model=PositionResponse)
async def init_stock_position(stock_code: str, _=Depends(require_trader)):
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
