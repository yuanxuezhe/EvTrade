"""
order_place.py — POST /api/orders/place 下单端点

行为（v6 重构）：
- 先 DB 后 RPC
- INSERT status=48 (order_id 空) → 调 ord_stk(remark=order_no)
- broker 带回 order_id 时 UPDATE 写入
- ord_cfm 到达时由 _infer_order_status 推断 status

依赖（late import 拿 patched symbol 用于 monkeypatch 测试）：
- from server.api.orders import ord_stk, ws_manager
"""
import logging

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from server.auth.deps import get_current_user
from server.enums.trading import PriceType
from server.db import get_db
from server.models.orm import Order, SysStatus
from server.models.user import User
from server.services.guards import require_trader, require_trading_day, require_trading_session
from server.services.order_no import next_order_no
from server.services.push_helpers import format_ts
from server.services.t0 import calc_net_amount, calc_t0_volume, get_fee_config
from server.api._order_schemas import (
    PlaceOrderRequest,
    PlaceOrderResponse,
    _to_order_out,
)

log = logging.getLogger(__name__)


def register_place(router):
    """注册 POST /place 端点到 FastAPI router。"""

    @router.post("/place", response_model=PlaceOrderResponse,
                 dependencies=[Depends(require_trader), Depends(require_trading_day), Depends(require_trading_session)])
    async def place_order(req: PlaceOrderRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
        """下单（标准：先本地后柜台）"""
        # Late import 拿 patched symbol（test_orders_api.py monkeypatch 路径）
        from server.api.orders import ord_stk, ws_manager

        if req.order_type not in ("23", "24"):
            raise HTTPException(status_code=400, detail={"code": "BAD_ORDER_TYPE", "msg": "order_type 必须 23(买) 24(卖)"})

        # 1. 取交易日 + order_no（v7：幂等改由 order_no 单调递增保证）
        trd_date = db.query(SysStatus).filter_by(status='active').first().trd_date

        # 2. T0 配平
        direction = "BUY" if req.order_type == "23" else "SELL"
        adjusted = calc_t0_volume(req.volume, req.t0_coefficient, direction)
        if adjusted <= 0:
            raise HTTPException(
                status_code=400,
                detail={"code": "VOLUME_TOO_SMALL", "msg": "T0 配平后 0 股 (目标 {} × 系数 {})".format(req.volume, req.t0_coefficient)}
            )

        # 3. 算费
        fee_cfg = get_fee_config()
        gross, net = calc_net_amount(req.price, adjusted, fee_cfg, direction)

        # 4. INSERT status=48（待报）
        order_no = next_order_no(db)
        order = Order(
            trd_date=trd_date,
            order_no=order_no,
            user_def=req.user_def,
            stock_code=req.stock_code, order_type=req.order_type,
            price_type=req.price_type, price=req.price, volume=adjusted,
            traded_volume=0, traded_amount=0.0, avg_price=0.0,
            status="48", status_msg="待报",
            order_time=format_ts(tz='local'),  # v10: "YYYY-MM-DD HH:MM:SS.fff"
        )
        db.add(order)
        db.commit()
        db.refresh(order)

        # 5. 调 RPC
        try:
            ack = await ord_stk(
                stock_code=req.stock_code, order_type=req.order_type,
                price_type=req.price_type, price=req.price, volume=adjusted,
                remark=order_no,
            )
        except Exception as e:
            log.exception("place_order RPC failed: stock=%s order_no=%s", req.stock_code, order_no)
            order.status = "55"
            order.status_msg = "RPC 失败: {}".format(e)
            db.commit()
            db.refresh(order)
            return PlaceOrderResponse(
                code=1, msg="柜台调用失败",
                order=_to_order_out(order),
                list=[_to_order_out(order)],
                error=str(e), t0_adjusted_volume=adjusted,
            )

        # 6. 解析 ack（成功 → 49；失败 → 55）
        ack_code = int(ack.get("code", -1))
        ack_list = ack.get("list", [])
        broker_order_id = ""
        if ack_code == 0 and ack_list and isinstance(ack_list[0], dict):
            broker_order_id = str(ack_list[0].get("order_id", ""))
            if broker_order_id:
                order.order_id = broker_order_id
            # status 由 _infer_order_status 推断更准;但 ack 成功就先写 49,ord_cfm 来了会重算
            order.status = "49"
            order.status_msg = "已报"
        else:
            order.status = "55"
            order.status_msg = ack.get("msg", "柜台拒单")
        db.commit()
        db.refresh(order)

        # 7. 推 WS
        # v8 增: payload 加 trd_date + order_no + remark,前端 holdings 推送守门用
        try:
            await ws_manager.broadcast("order_update", {
                "trd_date": order.trd_date,
                "order_no": order.order_no,
                "remark": order.order_no,
                "order_id": order.order_id or "",
                "stock_code": order.stock_code,
                "status": order.status,
                "status_msg": order.status_msg,
                "volume": order.volume,
                "traded_volume": order.traded_volume,
            })
        except Exception as e:
            log.warning("WS push failed: %s", e)

        return PlaceOrderResponse(
            code=0 if order.status == "49" else 1,
            msg=order.status_msg,
            order=_to_order_out(order),
            list=[_to_order_out(order)],
            broker_order_id=broker_order_id,
            fee_breakdown={"gross": gross, "net": net, "commission_rate": fee_cfg.commission_rate},
            t0_adjusted_volume=adjusted,
        )
