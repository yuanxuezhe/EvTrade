from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional, Any, Dict
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


# 内存中占位用的英文状态 → 柜台数字（保持前后端都用原始数字）
_INMEM_TO_NUMERIC = {
    "pending":   "49",  # 柜台 pending_report 待报
    "cancelled": "54",  # 柜台 cancelled 已撤
    "filled":    "56",
    "rejected":  "57",
}


def _normalize_status(status: str) -> str:
    """统一委托状态为柜台原始数字。

    RPC 路径直接是柜台返回的字符串数字（"48"-"57" / "255"）；
    in-memory 路径存的是英文占位 key，需要反向映射成同样的数字串，
    否则前端要兼容两套表示。
    """
    if status is None:
        return ""
    s = str(status).strip()
    if not s:
        return ""
    # 已是数字 → 原样返回
    if s.isdigit():
        return s
    # in-memory 英文 key → 数字
    return _INMEM_TO_NUMERIC.get(s, s)


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
        status=_normalize_status(o.get("status", "")),
        traded_volume=o.get("traded_volume", 0),
        traded_price=o.get("traded_price", 0.0),
        order_time=o.get("order_time", ""),
        order_remark=str(o.get("order_remark", "")),
        status_msg=str(o.get("status_msg", "")),
    )


@router.get("", response_model=OrderRpcResponse)
async def list_orders(stock_code: Optional[str] = None, use_rpc: bool = True):
    if use_rpc:
        try:
            data = await qry_orders()
            code = int(data.get("code", -1))
            msg = str(data.get("msg", ""))
            items = []
            if code == 0:
                for o in data.get("list", []):
                    mapped = _row_to_order_response(o, stock_code)
                    if mapped is not None:
                        items.append(mapped)
            return OrderRpcResponse(code=code, msg=msg, list=items)
        except Exception as e:
            print(f"qry_orders error: {e}")
            return OrderRpcResponse(code=-1, msg=str(e), list=[])

    orders = get_orders(stock_code)
    return OrderRpcResponse(
        code=0,
        msg="",
        list=[
            OrderResponse(
                order_id=o.order_id,
                stock_code=o.stock_code,
                order_type=o.order_type,
                volume=o.volume,
                price=o.price,
                price_type=o.price_type,
                status=_normalize_status(o.status),
                traded_volume=o.traded_volume,
                traded_price=o.traded_price,
                order_time=o.order_time,
                order_remark=o.order_remark,
                status_msg=""
            )
            for o in orders
        ],
    )


@router.post("", response_model=OrderResponse)
async def create_order(order_data: OrderCreate, _=Depends(require_trader)):
    order = Order(
        order_id=str(uuid.uuid4())[:8],
        stock_code=order_data.stock_code,
        order_type=order_data.order_type,
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
        order_type=order.order_type,
        volume=order.volume,
        price=order.price,
        price_type=order.price_type,
        status=order.status,
        traded_volume=order.traded_volume,
        traded_price=order.traded_price,
        order_time=order.order_time,
        order_remark=order.order_remark,
        status_msg=order.status_msg
    )


@router.post("/place", response_model=OrderAckRpcResponse)
async def place_order(order_data: OrderCreate, _=Depends(require_trader)):
    """通过RPC下单 ord_stk（等待柜台应答）"""
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
        print(f"ord_stk error: {e}")
        return OrderAckRpcResponse(code=-1, msg=str(e), list=[])


@router.delete("/{order_id}")
async def cancel_order(order_id: str, _=Depends(require_trader)):
    update_order_status(order_id, "cancelled")
    return {"order_id": order_id, "status": "cancelled"}
