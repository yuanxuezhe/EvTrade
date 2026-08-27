"""
cancel.py — DELETE /api/orders/{order_no} 撤单端点

关键架构（broker 协议约束）:
- cancel_ord RPC 只接 order_id,没 remark 字段
- broker ord_cfm 的 remark 永远回带**原** order_no,不是我们新分配的
- 因此 cancel-row 是纯本地,由本端点全权管理
- DELETE 必须手动 ws_manager.broadcast("order_update", ...) 给前端

5 步流程:
  1. Pre-checks (status ∈ {48,49,50}、order_id 存在):不插行,直接返
  2. INSERT cancel-row (commit 立即落库避免 RPC 异常时孤儿)
     raw_id = orig.order_no（结构化冗余；user_def 仍 = "CANCEL:{orig.order_no}"）
  3. Call RPC (try/except 捕获网络异常)
  4. 分支:
     - ack.code == 0 → cancel_row.status="54",同时 INSERT cancel-trade
     - ack.code != 0 → cancel_row.status="55" (废单,审计保留)
     - RPC 抛异常 → 同上 status="55"
  5. WS broadcast: 始终推 order_update,仅成功时推 trade_update（payload 含 raw_id）

- insert_cancel_row / next_order_no (server.repo.orders) 内部已走 tables

依赖（late import 拿 patched symbol 用于 monkeypatch 测试）：
- from server.api.orders import rpc_cancel_order, ws_manager
"""
import logging
import time as _time
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Query

from server.auth.deps import get_current_user
from server.services.guards import require_trader, require_trading_day, require_trading_session
from server.api.deps import require_rpc_ok  # RPC 健康检查 (统一 deps)
from server.repo.orders import next_order_no, insert_cancel_row  # insert_cancel_row helper
from server.utils.time import format_ts
from server.api.orders.schemas import (
    CancelResponse,
    _to_order_out,
)
from server.tables import Orders, Trades, Row

log = logging.getLogger(__name__)

# status_msg 列是 String(255), 撤单失败时 broker 可能返回含
#   xtquant 内部对象 repr 的长字符串 (例如 "<xtpythonclient.CancelOrderStockReq object at 0x...>")
#   写入时直接 1406 Data too long → API 500. 集中截断到 250 字符 (保留 5 字符余量)
_MSG_MAX_LEN = 250


def _safe_status_msg(s, limit: int = _MSG_MAX_LEN) -> str:
    """截断 status_msg 到 DB 列允许长度, 避免 DataError 1406 让撤单 API 500."""
    if s is None:
        return ""
    s = str(s)
    if len(s) <= limit:
        return s
    return s[: limit - 1] + "…"  # 末尾加省略号, 总长恰好 limit


def register_cancel(router):
    """注册 DELETE /{order_no} 端点到 FastAPI router。"""

    @router.delete("/{order_no}", response_model=CancelResponse,
                   dependencies=[Depends(require_trader), Depends(require_trading_day),
                                 Depends(require_trading_session),
                                 Depends(require_rpc_ok)])  # 调 RPC 前阻塞
    async def cancel_order(order_no: str, trd_date: str = Query(..., description="8 位数字 YYYYMMDD"),
                          user: Row = Depends(get_current_user)):
        """撤单（本地代理 cancel-order 行 + cancel-trade 行 + raw_id 写入）

        全部走 server.tables.*
        """
        # Late import 拿 patched symbol
        from server.api.orders import rpc_cancel_order, ws_manager

        # ── 1. Pre-checks ──
        # Orders.query_one (复合 PK)
        order = Orders.query_one(trd_date=trd_date, order_no=order_no)
        if not order:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "msg": "委托 {} 不存在".format(order_no)})

        if order.status not in ("50", "55"):  # 仅 已报/部成 可撤 (48/49 broker order_id 未回报)
            return CancelResponse(
                code=1, msg="当前 status={} 不可撤 (仅已报/部成可撤)".format(order.status),
                order_id=order.order_id or "", cancel_order=None,
                error="status {} non-cancellable".format(order.status),
            )

        if not order.order_id:
            return CancelResponse(
                code=1, msg="broker 尚未回报 order_id,暂不可撤",
                order_id="", cancel_order=None, error="BROKER_NOT_READY",
            )

        # ── 2. INSERT cancel-row (LOCAL-ONLY, 走 insert_cancel_row helper) ──
        # next_order_no / insert_cancel_row 内部已走 tables; 不再传 db
        cancel_order_no = next_order_no()
        cancel_row = insert_cancel_row(
            orig=order,
            cancel_order_no=cancel_order_no,
            raw_id=order_no,  # 结构化冗余字段 = orig.order_no
        )

        # ── 3. Call broker cancel_ord RPC ──
        ack = None
        rpc_error = None
        try:
            ack = await rpc_cancel_order(order_id=order.order_id)
            ack_code = int(ack.get("code", -1))
        except Exception as e:
            log.exception("cancel_order RPC exception: orig_order_no=%s err=%s", order_no, e)
            ack_code = -1
            rpc_error = str(e)

        # ── 4. Outcome branches ──
        cancelled_qty = max(0, (order.volume or 0) - (order.traded_volume or 0))
        cancel_trade_price = order.avg_price or order.price

        cancel_trade = None
        if ack_code == 0:
            # 成功 → broker 54 已撤
            # Row 字段赋值 + obj.update(Orders, pk=...)
            cancel_row.status = "54"
            cancel_row.status_msg = "已撤"
            cancel_row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            cancel_row.update(Orders, trd_date=trd_date, order_no=cancel_order_no)

            # change system-delegation-price-fill-calc: R1 撤单成功 → orig.cancelled_volume 一次性抹平到 volume
            order.cancelled_volume = order.volume
            order.update(Orders, trd_date=trd_date, order_no=order_no)

            if cancelled_qty > 0:
                cancel_trade_id = "CANCEL-{}-{}".format(cancel_order_no, int(_time.time()))
                # Trades.add_one(dict)
                cancel_trade = Trades.add_one({
                    "trd_date": trd_date,
                    "order_no": cancel_order_no,
                    "trade_id": cancel_trade_id,        # 合成
                    "stock_code": order.stock_code,
                    "order_type": order.order_type,
                    "price": cancel_trade_price,
                    "volume": cancelled_qty,
                    "amount": cancel_trade_price * cancelled_qty,
                    "trade_time": format_ts(tz='local'),  # "YYYY-MM-DD HH:MM:SS.fff"
                    "trade_type": 1,                    # ★ 撤单成交标记
                })
        else:
            # 失败 (ack.code != 0 或 RPC 异常) → broker 57 废单(审计保留,不插 trade)
            cancel_row.status = "57"
            cancel_row.status_msg = _safe_status_msg(
                (ack.get("msg") if ack else None) or rpc_error or "撤单失败"
            )
            cancel_row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            cancel_row.update(Orders, trd_date=trd_date, order_no=cancel_order_no)

        # ── 5. WS broadcast (broker 不会推这个 row,必须手动) ──
        # 统一 _broadcast_order_cfm helper, 包装 type='ord_cfm' + data,
        # 前端 ws_dispatch.js t='ord_cfm' 才能正确 parse (裸 dict 之前被丢).
        try:
            from server.services.push.order_broadcast import _broadcast_order_cfm
            _broadcast_order_cfm(cancel_row, trace_id=cancel_row.order_no)
            if cancel_trade:
                from server.services.push.helpers import _trade_to_out_dict
                await ws_manager.broadcast("trade_update", {
                    "type": "trd_cfm",
                    "channel": "trade_update",
                    "ts": format_ts(tz="local"),
                    "data": _trade_to_out_dict(cancel_trade),
                })
        except Exception as e:
            log.warning("WS broadcast cancel failed: %s", e)

        # ── 6. Return ──
        if ack_code == 0:
            return CancelResponse(
                code=0, msg="撤单请求已发",
                order_id=order.order_id, cancel_ack=ack,
                cancel_order=_to_order_out(cancel_row),
            )
        else:
            return CancelResponse(
                code=1, msg=cancel_row.status_msg,
                order_id=order.order_id, cancel_ack=ack,
                cancel_order=_to_order_out(cancel_row),
                error=rpc_error or (ack.get("msg") if ack else None) or "cancel failed",
            )
