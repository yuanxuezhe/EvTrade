"""
handlers.py — 业务 RPC 调用入口

每个 qry_* / ord_* / cancel_* 函数都遵循统一模式：
  1. 拿全局 client
  2. 调 client.call(func_name, headers, values)
  3. 用对应 _parse_* 解析应答

业务函数（供 api/orders.py / services/reconcile.py 等上层调用）：
- qry_asset / qry_orders / qry_trades / qry_positions: 查询类
- ord_stk: 下单
- cancel_order: 撤单
"""
from typing import Any, Dict, Optional

from server.config import settings
from server.rpc.transport import get_rpc_client
from server.rpc.parsers_business import (
    _parse_asset,
    _parse_order_ack,
    _parse_orders,
    _parse_positions,
    _parse_trades,
)


async def qry_asset() -> Dict[str, Any]:
    """查询资金 qry_ast → {code, msg, list:[asset_dict]}"""
    client = await get_rpc_client()
    pkt = await client.call("qry_ast")
    return _parse_asset(pkt)


async def qry_orders() -> Dict[str, Any]:
    """查询委托 qry_ord → {code, msg, list:[order_dict, ...]}"""
    client = await get_rpc_client()
    pkt = await client.call("qry_ord")
    return _parse_orders(pkt)


async def qry_trades() -> Dict[str, Any]:
    """查询成交 qry_mch → {code, msg, list:[trade_dict, ...]}"""
    client = await get_rpc_client()
    pkt = await client.call("qry_mch")
    return _parse_trades(pkt)


async def qry_positions() -> Dict[str, Any]:
    """查询持仓 qry_pos → {code, msg, list:[pos_dict, ...]}"""
    client = await get_rpc_client()
    pkt = await client.call("qry_pos")
    return _parse_positions(pkt)


async def ord_stk(
    stock_code: str,
    volume: int,
    price_type: int,
    price: float,
    order_type: str,
    remark: Optional[str] = None,
    msgid_meta: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """下单 ord_stk（等待柜台应答）

    协议同 qry_*：第 1 结果集 code/msg；第 2 结果集为下单回报（如 order_id）。
    成交细节仍通过 EvTrade.Test.Push 队列异步推送（ord_cfm / trd_cfm）。

    参数：
      order_type  柜台买卖类型数字串，股票场景：23=买入，24=卖出
      price_type  柜台价格类型数字：
                    5=最新价 11=指定价(限价) 14=对手价 44=市价 ...
      remark      委托备注，柜台透传；不传时取 settings.ORDER_REMARK（默认 "EvTrade.Test"）
      msgid_meta (v84): dict 含 order_no / trd_date / stock_code。
        提供后 transport 层在收到 code!=0 应答时按 msgid 找到原 order_no 异步更新为废单。
        不提供时, 废单路径失效 (place.py 同步 await 路径仍会处理 code!=0 → status=57).
    """
    client = await get_rpc_client()
    if remark is None:
        remark = settings.ORDER_REMARK
    pkt = await client.call(
        "ord_stk",
        headers="stock_code,volume,price_type,price,order_type,remark",
        values={
            "stock_code": stock_code,
            "volume": str(volume),
            "price_type": str(price_type),
            "price": str(price),
            "order_type": order_type,
            "remark": remark,
        },
        msgid_meta=msgid_meta,
    )
    return _parse_order_ack(pkt)


async def cancel_order(order_id: str) -> Dict[str, Any]:
    """撤单 cxl_ord（柜台协议：仅 order_id，无 market / stock_code）

    v__ (REQ-TRADE-033): 柜台 xtquant API 签名是 (acc, order_id) 二参,
    handler 内部不读任何额外字段. 服务端 RPC 层 packet 只含 order_id.
    """
    client = await get_rpc_client()
    pkt = await client.call(
        "cxl_ord",
        headers="order_id",
        values={"order_id": order_id},
    )
    return _parse_order_ack(pkt)
