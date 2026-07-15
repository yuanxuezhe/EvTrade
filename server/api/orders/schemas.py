"""
schemas.py — orders API 的 Pydantic schemas + Order→OrderOut helper

包含：
- PlaceOrderRequest: POST /place 入参
- OrderOut: 委托出参（含 v7 user_def / v8 cancelled_volume / v9 order_flag）
- PlaceOrderResponse: POST /place 响应（含 v8 list 字段冗余 1 行）
- ListOrdersResponse: GET / 和 GET /history 列表响应
- CancelResponse: DELETE /{order_no} 响应（含 v9 cancel_order 本地代理行）
- _to_order_out: Order → OrderOut 转换 helper（消除 3 处重复）
"""
from typing import List, Optional

from pydantic import BaseModel

from server.enums.trading import PriceType


class PlaceOrderRequest(BaseModel):
    user_def: str = ""                # 外部自定义信息透传（无业务约束）
    stock_code: str
    order_type: str          # 23=买 24=卖
    price_type: int = PriceType.FIX_PRICE  # 默认限价单
    price: float
    volume: int
    t0_coefficient: float = 1.0
    task_id: Optional[int] = None  # v18: 关联 t0_tasks.id (None = 游离单)


class OrderOut(BaseModel):
    order_id: str = ""  # 改:broker 未回报前为空串 (下单后 → ord_cfm 到达前的窗口期)
    user_def: str = ""  # v7:外部自定义信息透传（替代原 client_order_id）
    order_no: str
    trd_date: str
    stock_code: str
    order_type: str
    price_type: int
    price: float
    volume: int
    traded_volume: int
    traded_amount: float
    avg_price: float
    cancelled_volume: int = 0  # v8:累计撤单量（broker ord_cfm 累加）
    order_flag: int = 0  # v9:0=normal 1=cancel-order (本地代理撤单委托行)
    status: str
    status_msg: str
    order_time: str
    raw_id: Optional[str] = None  # v13 NEW: cancel-row 写 = 原 order_no；普通行 None
    task_id: Optional[int] = None  # v18 NEW: 关联 t0_tasks.id (None = 游离单)


class PlaceOrderResponse(BaseModel):
    code: int = 0
    msg: str = ""
    order: Optional[OrderOut] = None
    # v8: 统一 RPC 格式 list 字段（冗余 1 行，跟 GET /orders list 风格一致）
    #   - 前端 axios 拦截器解包后 res.data = list[0] = OrderOut
    #   - 保留 order 字段以兼容老代码
    list: List[OrderOut] = []
    broker_order_id: str = ""
    fee_breakdown: Optional[dict] = None
    t0_adjusted_volume: Optional[int] = None
    error: Optional[str] = None


class ListOrdersResponse(BaseModel):
    code: int = 0
    msg: str = ""
    list: List[OrderOut] = []
    total: int = 0


class CancelResponse(BaseModel):
    code: int = 0
    msg: str = ""
    order_id: str
    cancel_ack: Optional[dict] = None
    # v9: 本地代理的「撤单委托」行（pre-check 失败时为 None;成功/失败时含 status=53/55）
    cancel_order: Optional[OrderOut] = None
    error: Optional[str] = None


# v8 增:Order → OrderOut 转换（消除 3 处重复；list 包装由调用方做）
def _to_order_out(o):
    return OrderOut(
        order_id=o.order_id or "", user_def=o.user_def,
        order_no=o.order_no, trd_date=o.trd_date, stock_code=o.stock_code,
        order_type=o.order_type, price_type=o.price_type,
        price=o.price, volume=o.volume,
        traded_volume=o.traded_volume, traded_amount=o.traded_amount,
        avg_price=o.avg_price, cancelled_volume=o.cancelled_volume or 0,
        order_flag=o.order_flag or 0,
        status=o.status,
        status_msg=o.status_msg, order_time=o.order_time,
        raw_id=o.raw_id,  # v13 NEW: cancel-row 透传；普通行为 None
        task_id=o.task_id,  # v18 NEW: 透传到前端 task 视图
    )
