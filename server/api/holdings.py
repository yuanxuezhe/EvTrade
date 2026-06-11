from fastapi import APIRouter
from typing import List
from pydantic import BaseModel
from rpc.client import qry_positions

router = APIRouter()


class HoldingItem(BaseModel):
    stock_code: str
    last_vol: int
    volume: int
    available: int
    cost: float
    market_value: float


class HoldingsRpcResponse(BaseModel):
    code: int
    msg: str
    list: List[HoldingItem]


@router.get("", response_model=HoldingsRpcResponse)
async def list_holdings():
    """直接透传 qry_positions 的 6 个原始字段，不做任何派生/臆造。"""
    try:
        data = await qry_positions()
        code = int(data.get("code", -1))
        msg = str(data.get("msg", ""))
        items = []
        if code == 0:
            items = [HoldingItem(**p) for p in data.get("list", [])]
        return HoldingsRpcResponse(code=code, msg=msg, list=items)
    except Exception as e:
        print(f"qry_positions error: {e}")
        return HoldingsRpcResponse(code=-1, msg=str(e), list=[])
