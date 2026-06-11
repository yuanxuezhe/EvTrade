from fastapi import APIRouter
from typing import List, Optional
from pydantic import BaseModel
from rpc.client import qry_trades

router = APIRouter()

class TradeResponse(BaseModel):
    trade_id: str
    order_id: str
    stock_code: str
    # 柜台 order_type 数字串：股票 23=买入，24=卖出
    order_type: str
    volume: int
    price: float
    trade_time: str


class TradeRpcResponse(BaseModel):
    """成交查询统一返回 {code, msg, list}"""
    code: int
    msg: str
    list: List[TradeResponse]


def _row_to_trade_response(t: dict, stock_code_filter: Optional[str] = None) -> Optional[TradeResponse]:
    if stock_code_filter and t.get("stock_code") != stock_code_filter:
        return None
    return TradeResponse(
        trade_id=t.get("trade_id", ""),
        order_id=t.get("order_id", ""),
        stock_code=t.get("stock_code", ""),
        order_type=str(t.get("order_type", "")),
        volume=int(t.get("volume", 0) or 0),
        price=float(t.get("price", 0.0) or 0.0),
        trade_time=t.get("trade_time", ""),
    )


@router.get("", response_model=TradeRpcResponse)
async def list_trades(stock_code: Optional[str] = None):
    """成交查询走柜台 qry_mch，应答统一 {code, msg, list}。

    注意：之前用的是 services.trading.get_trades()，那个内存表
    trades_store 在实际流程中没有任何写入（WS push 只更新前端 store），
    所以查询永远返回空数组。改为 RPC 之后才能拉到真实的成交记录。
    """
    try:
        data = await qry_trades()
        code = int(data.get("code", -1))
        msg = str(data.get("msg", ""))
        items = []
        if code == 0:
            for t in data.get("list", []):
                mapped = _row_to_trade_response(t, stock_code)
                if mapped is not None:
                    items.append(mapped)
        return TradeRpcResponse(code=code, msg=msg, list=items)
    except Exception as e:
        print(f"qry_trades error: {e}")
        return TradeRpcResponse(code=-1, msg=str(e), list=[])