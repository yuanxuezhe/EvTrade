"""
order_cancel.py — DELETE /api/orders/{order_no} 撤单端点（v9 重写）

关键架构（broker 协议约束）:
- cancel_ord RPC 只接 order_id,没 remark 字段
- broker ord_cfm 的 remark 永远回带**原** order_no,不是我们新分配的
- 因此 cancel-row 是纯本地,由本端点全权管理
- DELETE 必须手动 ws_manager.broadcast("order_update", ...) 给前端

5 步流程:
  1. Pre-checks (status ∈ {48,49}、order_id 存在):不插行,直接返
  2. INSERT cancel-row (commit 立即落库避免 RPC 异常时孤儿)
  3. Call RPC (try/except 捕获网络异常)
  4. 分支:
     - ack.code == 0 → cancel_row.status="53",同时 INSERT cancel-trade
     - ack.code != 0 → cancel_row.status="55" (废单,审计保留)
     - RPC 抛异常 → 同上 status="55"
  5. WS broadcast: 始终推 order_update,仅成功时推 trade_update

依赖（late import 拿 patched symbol 用于 monkeypatch 测试）：
- from server.api.orders import rpc_cancel_order, ws_manager
"""
import logging
import time as _time
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Query
from sqlalchemy.orm import Session

from server.auth.deps import get_current_user
from server.db import get_db
from server.models.orm import Order, Trade
from server.models.user import User
from server.services.guards import require_trader, require_trading_day, require_trading_session
from server.services.order_no import next_order_no
from server.api._order_schemas import (
    CancelResponse,
    _to_order_out,
)

log = logging.getLogger(__name__)


def register_cancel(router):
    """注册 DELETE /{order_no} 端点到 FastAPI router。"""

    @router.delete("/{order_no}", response_model=CancelResponse,
                   dependencies=[Depends(require_trader), Depends(require_trading_day), Depends(require_trading_session)])
    async def cancel_order(order_no: str, trd_date: str = Query(..., description="8 位数字 YYYYMMDD"),
                          user: User = Depends(get_current_user), db: Session = Depends(get_db)):
        """撤单（v9 重写:本地代理 cancel-order 行 + cancel-trade 行）"""
        # Late import 拿 patched symbol
        from server.api.orders import rpc_cancel_order, ws_manager

        # ── 1. Pre-checks ──
        order = db.query(Order).filter_by(order_no=order_no, trd_date=trd_date).first()
        if not order:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "msg": "委托 {} 不存在".format(order_no)})

        if order.status not in ("48", "49"):
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

        # ── 2. INSERT cancel-row (LOCAL-ONLY) ──
        cancel_order_no = next_order_no(db)
        cancel_row = Order(
            trd_date=trd_date,
            order_no=cancel_order_no,
            order_id=None,                    # broker 永远不报这个 row
            user_def="CANCEL:{}".format(order_no),  # 关联: cancel → orig
            stock_code=order.stock_code,       # 镜像
            order_type=order.order_type,       # 镜像 23/24
            price_type=order.price_type,       # 镜像
            price=order.price,                 # 镜像
            volume=0,                          # ★ 用户选择: 零委托量
            traded_volume=0, traded_amount=0.0, avg_price=0.0,
            cancelled_volume=0,
            order_flag=1,                      # ★ 撤单委托标记
            status="48",                       # sentinel 待发
            status_msg="撤单请求中",
            order_time=datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec='seconds'),
        )
        db.add(cancel_row)
        db.commit()
        db.refresh(cancel_row)

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
            # 成功 → 53 已撤
            cancel_row.status = "53"
            cancel_row.status_msg = "已撤"
            cancel_row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)

            if cancelled_qty > 0:
                cancel_trade_id = "CANCEL-{}-{}".format(cancel_order_no, int(_time.time()))
                cancel_trade = Trade(
                    trd_date=trd_date,
                    order_no=cancel_order_no,
                    trade_id=cancel_trade_id,        # 合成
                    stock_code=order.stock_code,
                    order_type=order.order_type,
                    price=cancel_trade_price,
                    volume=cancelled_qty,
                    amount=cancel_trade_price * cancelled_qty,
                    trade_time=datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec='seconds'),
                    trade_type=1,                    # ★ 撤单成交标记
                )
                db.add(cancel_trade)
            db.commit()
            db.refresh(cancel_row)
            if cancel_trade:
                db.refresh(cancel_trade)
        else:
            # 失败 (ack.code != 0 或 RPC 异常) → 55 废单(审计保留,不插 trade)
            cancel_row.status = "55"
            cancel_row.status_msg = (
                (ack.get("msg") if ack else None) or rpc_error or "撤单失败"
            )
            cancel_row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            db.commit()
            db.refresh(cancel_row)

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
