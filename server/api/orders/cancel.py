"""
cancel.py — DELETE /api/orders/{order_no} 撤单端点（v9 重写 + v13 增 raw_id）

关键架构（broker 协议约束）:
- cancel_ord RPC 只接 order_id,没 remark 字段
- broker ord_cfm 的 remark 永远回带**原** order_no,不是我们新分配的
- 因此 cancel-row 是纯本地,由本端点全权管理
- DELETE 必须手动 ws_manager.broadcast("order_update", ...) 给前端

5 步流程:
  1. Pre-checks (status ∈ {48,49,50}、order_id 存在):不插行,直接返
  2. INSERT cancel-row (commit 立即落库避免 RPC 异常时孤儿)
     v13 增 raw_id = orig.order_no（结构化冗余；user_def 仍 = "CANCEL:{orig.order_no}"）
  3. Call RPC (try/except 捕获网络异常)
  4. 分支:
     - ack.code == 0 → cancel_row.status="54",同时 INSERT cancel-trade
     - ack.code != 0 → cancel_row.status="55" (废单,审计保留)
     - RPC 抛异常 → 同上 status="55"
  5. WS broadcast: 始终推 order_update,仅成功时推 trade_update（payload 含 raw_id）

v81 tables-migration:
- 删 Depends(get_db) + sqlalchemy.orm.Session
- db.query(Order).filter_by(...) → Orders.query_one(trd_date=..., order_no=...)
- m.x = val; db.commit() → obj.x = val; obj.update(Orders, **pk)
- db.add(cancel_trade); db.commit() → Trades.add_one({...})
- db.refresh(obj) → 删 (Row 已是 dict-like)
- insert_cancel_row / next_order_no (server.repo.orders) 内部已迁 tables

依赖（late import 拿 patched symbol 用于 monkeypatch 测试）：
- from server.api.orders import rpc_cancel_order, ws_manager
"""
import logging
import time as _time
from datetime import datetime, timezone  # noqa: F401  # kept for legacy refs

from fastapi import Depends, HTTPException, Query

from server.auth.deps import get_current_user
from server.models.user import User
from server.services.guards import require_trader, require_trading_day, require_trading_session
from server.repo.orders import next_order_no, insert_cancel_row  # v13: insert_cancel_row helper (v80.3 迁 tables)
from server.utils.time import format_ts
from server.api.orders.schemas import (
    CancelResponse,
    _to_order_out,
)
from server.tables import Orders, Trades

log = logging.getLogger(__name__)

# v77.4 fix: status_msg 列是 String(255), 撤单失败时 broker 可能返回含
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
                   dependencies=[Depends(require_trader), Depends(require_trading_day), Depends(require_trading_session)])
    async def cancel_order(order_no: str, trd_date: str = Query(..., description="8 位数字 YYYYMMDD"),
                          user: User = Depends(get_current_user)):
        """撤单（v9 重写:本地代理 cancel-order 行 + cancel-trade 行；v13 增 raw_id 写入）

        v81 tables-migration: 删 Depends(get_db), 全部走 server.tables.*
        """
        # Late import 拿 patched symbol
        from server.api.orders import rpc_cancel_order, ws_manager

        # ── 1. Pre-checks ──
        # v81 tables-migration: Orders.query_one (复合 PK) 替代 db.query(Order).filter_by(...).first()
        order = Orders.query_one(trd_date=trd_date, order_no=order_no)
        if not order:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "msg": "委托 {} 不存在".format(order_no)})

        if order.status not in ("48", "49", "50"):  # v11: 含 broker 50=已报也可撤
            return CancelResponse(
                code=1, msg="当前 status={} 不可撤".format(order.status),
                order_id=order.order_id or "", cancel_order=None,
                error="status {} non-cancellable".format(order.status),
            )

        if not order.order_id:
            return CancelResponse(
                code=1, msg="broker 尚未回报 order_id,暂不可撤",
                order_id="", cancel_order=None, error="BROKER_NOT_READY",
            )

        # ── 2. INSERT cancel-row (LOCAL-ONLY, v13 用 insert_cancel_row helper) ──
        # v81 tables-migration: next_order_no / insert_cancel_row 内部已走 tables; 不再传 db
        cancel_order_no = next_order_no()
        cancel_row = insert_cancel_row(
            orig=order,
            cancel_order_no=cancel_order_no,
            raw_id=order_no,  # v13 NEW: 结构化冗余字段 = orig.order_no
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
            # 成功 → broker 54 已撤 (v11: 替代本地推断码 53)
            # v81 tables-migration: Row 字段赋值 + obj.update(Orders, pk=...) 替代 db.commit() + db.refresh()
            cancel_row.status = "54"
            cancel_row.status_msg = "已撤"
            cancel_row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            cancel_row.update(Orders, trd_date=trd_date, order_no=cancel_order_no)

            # change system-delegation-price-fill-calc: R1 撤单成功 → orig.cancelled_volume 一次性抹平到 volume
            order.cancelled_volume = order.volume
            order.update(Orders, trd_date=trd_date, order_no=order_no)

            if cancelled_qty > 0:
                cancel_trade_id = "CANCEL-{}-{}".format(cancel_order_no, int(_time.time()))
                # v81 tables-migration: Trades.add_one(dict) 替代 db.add(Trade); db.commit()
                cancel_trade = Trades.add_one({
                    "trd_date": trd_date,
                    "order_no": cancel_order_no,
                    "trade_id": cancel_trade_id,        # 合成
                    "stock_code": order.stock_code,
                    "order_type": order.order_type,
                    "price": cancel_trade_price,
                    "volume": cancelled_qty,
                    "amount": cancel_trade_price * cancelled_qty,
                    "trade_time": format_ts(tz='local'),  # v10: "YYYY-MM-DD HH:MM:SS.fff"
                    "trade_type": 1,                    # ★ 撤单成交标记
                })
        else:
            # 失败 (ack.code != 0 或 RPC 异常) → broker 57 废单(审计保留,不插 trade, v11 替代本地码 55)
            cancel_row.status = "57"
            cancel_row.status_msg = _safe_status_msg(
                (ack.get("msg") if ack else None) or rpc_error or "撤单失败"
            )
            cancel_row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            cancel_row.update(Orders, trd_date=trd_date, order_no=cancel_order_no)

        # ── 5. WS broadcast (broker 不会推这个 row,必须手动) ──
        try:
            await ws_manager.broadcast("order_update", {
                "trd_date": cancel_row.trd_date,
                "order_no": cancel_row.order_no,
                "remark": cancel_row.order_no,
                "order_id": cancel_row.order_id or "",
                "stock_code": cancel_row.stock_code,
                "status": cancel_row.status,
                "status_msg": cancel_row.status_msg,
                "volume": cancel_row.volume,
                "traded_volume": cancel_row.traded_volume,
                "order_flag": cancel_row.order_flag,
                "user_def": cancel_row.user_def,
                "raw_id": cancel_row.raw_id,  # v13 NEW: 透传结构化 raw_id
            })
            if cancel_trade:
                await ws_manager.broadcast("trade_update", {
                    "trd_date": trd_date,
                    "trade_id": cancel_trade.trade_id,
                    "order_no": cancel_trade.order_no,
                    "stock_code": cancel_trade.stock_code,
                    "order_type": cancel_trade.order_type,
                    "price": cancel_trade.price,
                    "volume": cancel_trade.volume,
                    "amount": cancel_trade.amount,
                    "trade_time": cancel_trade.trade_time,
                    "trade_type": cancel_trade.trade_type,
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
