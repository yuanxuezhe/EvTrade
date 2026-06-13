from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional, Any, Dict
from pydantic import BaseModel
from rpc.client import qry_orders, ord_stk, cancel_order as rpc_cancel_order
from auth.deps import require_trader
import logging

log = logging.getLogger(__name__)

router = APIRouter()

class OrderCreate(BaseModel):
    stock_code: str
    # 柜台 order_type 数字串：股票 23=买入，24=卖出
    order_type: str
    volume: int
    price: float
    # 柜台 price_type 数字：5=最新价 11=指定价 14=对手价 44=市价 ...
    price_type: int = 11

class OrderResponse(BaseModel):
    order_id: str
    stock_code: str
    # 柜台 order_type 数字串：股票 23=买入，24=卖出
    order_type: str
    volume: int
    price: float
    # 柜台 price_type 数字：5=最新价 11=指定价 14=对手价 44=市价 ...
    price_type: int
    status: str
    traded_volume: int
    traded_price: float
    order_time: str
    # 柜台返回的废单/撤单原因说明
    order_remark: str = ""
    # 柜台废单原因文本（专用于废单等终端态）
    status_msg: str = ""


class OrderRpcResponse(BaseModel):
    code: int
    msg: str
    list: List[OrderResponse]


class OrderAckRpcResponse(BaseModel):
    """下单/撤单应答：list 元素结构由柜台决定，原样透传 dict。"""
    code: int
    msg: str
    list: List[Dict[str, Any]]


def _row_to_order_response(o: dict, stock_code_filter: Optional[str] = None) -> Optional[OrderResponse]:
    if stock_code_filter and o.get("stock_code") != stock_code_filter:
        return None
    return OrderResponse(
        order_id=o.get("order_id", ""),
        stock_code=o.get("stock_code", ""),
        order_type=str(o.get("order_type", "")),
        volume=o.get("volume", 0),
        price=o.get("price", 0.0),
        price_type=int(o.get("price_type", 11)),
        status=str(o.get("status", "")),
        traded_volume=o.get("traded_volume", 0),
        traded_price=o.get("traded_price", 0.0),
        order_time=o.get("order_time", ""),
        order_remark=str(o.get("order_remark", "")),
        status_msg=str(o.get("status_msg", "")),
    )


@router.get("", response_model=OrderRpcResponse)
async def list_orders(stock_code: Optional[str] = None):
    """查委托列表（柜台 RPC 单一数据源，无内存占位）"""
    try:
        data = await qry_orders()
    except Exception as e:
        log.exception("qry_orders error: %s", e)
        return OrderRpcResponse(code=-1, msg=str(e), list=[])

    code = int(data.get("code", -1))
    msg = str(data.get("msg", ""))
    items: List[OrderResponse] = []
    if code == 0:
        for o in data.get("list", []):
            mapped = _row_to_order_response(o, stock_code)
            if mapped is not None:
                items.append(mapped)
    return OrderRpcResponse(code=code, msg=msg, list=items)


@router.post("/place", response_model=OrderAckRpcResponse)
async def place_order(order_data: OrderCreate, _=Depends(require_trader)):
    """通过 RPC 下单 ord_stk（等待柜台应答）"""
    try:
        result = await ord_stk(
            stock_code=order_data.stock_code,
            volume=order_data.volume,
            price_type=order_data.price_type,
            price=order_data.price,
            order_type=order_data.order_type
        )
        return OrderAckRpcResponse(
            code=int(result.get("code", -1)),
            msg=str(result.get("msg", "")),
            list=list(result.get("list", [])),
        )
    except Exception as e:
        log.exception("ord_stk error: %s", e)
        return OrderAckRpcResponse(code=-1, msg=str(e), list=[])


@router.delete("/{order_id}", response_model=OrderAckRpcResponse)
async def cancel_order_endpoint(order_id: str, _=Depends(require_trader)):
    """撤单：走柜台 cancel_ord RPC，状态变更由 push 队列异步通知 WS。"""
    try:
        result = await rpc_cancel_order(order_id)
    except Exception as e:
        log.exception("cancel_ord error: %s", e)
        return OrderAckRpcResponse(code=-1, msg=str(e), list=[])
    return OrderAckRpcResponse(
        code=int(result.get("code", -1)),
        msg=str(result.get("msg", "")),
        list=list(result.get("list", [])),
    )
