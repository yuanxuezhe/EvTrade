from fastapi import APIRouter
from typing import List
from pydantic import BaseModel
from rpc.client import qry_positions
import logging

log = logging.getLogger(__name__)

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
    """查持仓（柜台 RPC 单一数据源）"""
    try:
        data = await qry_positions()
    except Exception as e:
        log.exception("qry_positions error: %s", e)
        return PositionRpcResponse(code=-1, msg=str(e), list=[])

    code = int(data.get("code", -1))
    msg = str(data.get("msg", ""))
    items: List[PositionResponse] = []
    if code == 0:
        items = [_row_to_position(p) for p in data.get("list", [])]
    return PositionRpcResponse(code=code, msg=msg, list=items)
