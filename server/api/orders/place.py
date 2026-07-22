"""
place.py — POST /api/orders/place 下单端点

v77 (REQ-TRADE-028) 两阶段下单架构:
- 阶段 A: DB INSERT status=48 未报 → ws push + 立即 HTTP 应答 (含 status=48 OrderOut)
- 阶段 B: RPC 后台 task → DB UPDATE status=50/57 + ws push
  - RPC 成功 (ack.code==0): UPDATE status=50 + 写 broker_order_id + ws push
  - RPC 失败 (ack.code!=0): UPDATE status=57 + cancelled_volume=volume + ws push
  - RPC 异常 (timeout/broker down): UPDATE status=57 + ws push (status_msg="RPC 超时/异常: ...")

设计意图 (v77 变更前为同步阻塞):
- 旧: DB INSERT → RPC 阻塞 → DB UPDATE → ws push → HTTP 应答. broker 慢 → 应答慢 → 前端等.
- 新: DB INSERT → ws push status=48 → 立即 HTTP 应答. RPC 后台 fire-and-forget.
  - 前端拿到 status=48 立即渲染 "待回报"; ws 后续推 status=50/57 覆盖
  - broker 慢/超时不影响 HTTP 应答 (axios 15s timeout 仍兜底)
  - RPC 异常吞掉会丢委托, 必须 try/except + ws push + log.exception

v81 tables-migration:
- 删 Depends(get_db) × 2 (endpoint + _submit_rpc_async)
- 删 server.models.orm.Order / SysStatus / get_active_trd_date ORM 调用
- DB I/O 全部走 server.tables.* (Orders.add_one / Orders.query_one / Orders.update_one / T0Tasks.query_one)
- 交易日改用 server.repo.orders._get_active_trd_date (已迁到 tables 层)
- 插入 + 更新改为 Row 风格: obj.x = val; obj.update(Orders, **pk)

依赖 (late import 拿 patched symbol 用于 monkeypatch 测试):
- from server.api.orders import ord_stk, ws_manager
- 关键: asyncio.create_task 不能直接传 monkeypatched symbol, 必须用 late import 在 task 内取.
"""
import asyncio
import logging

from fastapi import Depends, HTTPException

from server.auth.deps import get_current_user
from server.models.user import User
from server.services.guards import require_trader, require_trading_day, require_trading_session
from server.repo.orders import (
    _get_active_trd_date,
    insert_pending_order,
    next_order_no,
)
from server.utils.time import format_ts
from server.services.t0 import calc_net_amount, calc_t0_volume, get_fee_config
from server.repo.stocks import GetStockInfo  # v80.1: 统一证券信息入口
from server.services.sysconfig import get_cantrd_stktypes  # v80
from server.tables import Orders, T0Tasks
from server.api.orders.schemas import (
    PlaceOrderRequest,
    PlaceOrderResponse,
    _to_order_out,
)
from server.services.push.helpers import _order_to_out_dict

log = logging.getLogger(__name__)


def register_place(router):
    """注册 POST /place 端点到 FastAPI router。"""

    @router.post("/place", response_model=PlaceOrderResponse,
                 dependencies=[Depends(require_trader), Depends(require_trading_day), Depends(require_trading_session)])
    async def place_order(req: PlaceOrderRequest, user: User = Depends(get_current_user)):
        """下单（v77 两阶段：DB 写入立即应答，RPC 后台异步回报）

        v81 tables-migration: 删 Depends(get_db), 全部走 server.tables.*
        """
        # Late import 拿 patched symbol（test_orders_api.py monkeypatch 路径）
        from server.api.orders import ord_stk, ws_manager

        if req.order_type not in ("23", "24"):
            raise HTTPException(status_code=400, detail={"code": "BAD_ORDER_TYPE", "msg": "order_type 必须 23(买) 24(卖)"})

        # v80: stktype 可交易校验 + 价格按 stock.scale 四舍五入
        # v80.1: 用 GetStockInfo() 一次性拿 stktype + scale
        info = GetStockInfo(req.stock_code)
        stktype = info["stktype"]
        allowed = get_cantrd_stktypes(user="0")
        if stktype not in allowed:
            raise HTTPException(
                status_code=403,
                detail={"code": "STK_TYPE_NOT_TRADABLE",
                        "msg": f"证券 {req.stock_code} 类型 {stktype} 不可交易 (允许: {sorted(allowed)})"}
            )
        scale = info["scale"]
        if scale > 6:
            scale = 2  # 兜底 (用户原话)
        if req.price is not None and req.price > 0:
            req.price = round(float(req.price), scale)

        # 1. 取交易日 + order_no（v7：幂等改由 order_no 单调递增保证）
        #    v_next: SysStatus 单行 (id=1). v81 tables-migration: 走 repo helper
        trd_date = _get_active_trd_date()
        if not trd_date:
            raise HTTPException(
                status_code=503,
                detail={"code": "TRADING_DAY_NOT_INIT", "msg": "未做日初处理，无法交易"},
            )

        # 2. T0 配平
        direction = "BUY" if req.order_type == "23" else "SELL"
        adjusted = calc_t0_volume(req.volume, req.t0_coefficient, direction)
        if adjusted <= 0:
            raise HTTPException(
                status_code=400,
                detail={"code": "VOLUME_TOO_SMALL", "msg": "T0 配平后 0 股 (目标 {} × 系数 {})".format(req.volume, req.t0_coefficient)}
            )

        # 3. 算费 (用 round 后的 price)
        fee_cfg = get_fee_config()
        gross, net = calc_net_amount(req.price, adjusted, fee_cfg, direction)

        # 3.5 v18: 若带 task_id, 验证 task 归属 + active (避免跨用户误绑定)
        #    v81 tables-migration: T0Tasks.query_one(id=...) 替代 db.query(T0Task).filter_by(id=...).first()
        if req.task_id is not None:
            task = T0Tasks.query_one(id=req.task_id)
            if not task or task.user_id != user.id or task.status != "active":
                raise HTTPException(
                    status_code=400,
                    detail={"code": "INVALID_TASK", "msg": f"task_id={req.task_id} 不存在/非本人/非 active"}
                )
            if task.stock_code != req.stock_code:
                raise HTTPException(
                    status_code=400,
                    detail={"code": "TASK_STOCK_MISMATCH",
                            "msg": f"task 的 stock_code={task.stock_code} 与下单 {req.stock_code} 不符"}
                )

        # 4. INSERT status=48（未报）
        #    v81 tables-migration: 用 insert_pending_order (Orders.add_one 封装), 返回 Row
        order_no = next_order_no()
        order = insert_pending_order(
            trd_date=trd_date,
            order_no=order_no,
            user_def=req.user_def,
            stock_code=req.stock_code,
            order_type=req.order_type,
            price_type=req.price_type,
            price=req.price,
            volume=adjusted,
        )
        # v66/v18: 补全 task_id + strategy_type (insert_pending_order 通用, 不含这俩)
        if req.task_id is not None or req.strategy_type:
            order.task_id = req.task_id
            order.strategy_type = req.strategy_type
            order.update(Orders, trd_date=trd_date, order_no=order_no)

        # 5. v77: 阶段 A — 立即 ws push status=48 (前端立即显示 "未报")
        #   先 ws 后 HTTP 应答: 前端 ws 收到 + axios 拿到 response 都立即 _upsertToHoldings
        #   metaMerge (v76 修复) 保证 4 累计字段透传, 表格立即正确显示 status=48 未报委托.
        try:
            asyncio.ensure_future(ws_manager.broadcast("order_update", _order_to_out_dict(order)))
        except Exception as e:
            log.warning("ws push (status=48) failed: %s", e)

        # 6. v77: 阶段 B — RPC 后台 task (fire-and-forget)
        #   asyncio.create_task 不会阻塞 HTTP 应答; broker 慢/超时不影响前端.
        #   关键: task 内 late import 拿 patched ord_stk/ws_manager (test_orders_api.py monkeypatch).
        #   trd_date/order_no 捕获到闭包 (闭包避免 Row detached 问题).
        #   注: Orders 表 (trd_date, order_no) 联合 PK 定位
        _captured_trd_date = trd_date
        asyncio.create_task(_submit_rpc_async(order_no, _captured_trd_date))

        # 7. v77: 立即 HTTP 应答 (含 status=48 OrderOut)
        #   code=0 表示"DB 写入成功, RPC 已调度" (前端 v77 兼容: 此时代码=48 委托还未被 broker 确认)
        #   msg 明确告知前端 "DB 已写入, broker 回报中" 区别于 code=1 broker 拒单.
        return PlaceOrderResponse(
            code=0, msg="DB 已写入, broker 回报中 (v77 异步模式)",
            order=_to_order_out(order),
            list=[_to_order_out(order)],
            broker_order_id="",  # broker 回报后由 _submit_rpc_async 写入, 后续 ws push 推送
            fee_breakdown={"gross": gross, "net": net, "commission_rate": fee_cfg["commission_rate"]},
            t0_adjusted_volume=adjusted,
        )


async def _submit_rpc_async(order_no: str, trd_date: str):
    """
    v77: RPC 异步执行函数 (阶段 B 后台 task)

    流程:
    1. v81 tables-migration: 删 db = SessionLocal(); 改 Orders.query_one + Orders.update_one (自带引擎)
    2. late import 拿 patched ord_stk/ws_manager (monkeypatch 测试兼容)
    3. 调 broker ord_stk, remark=order_no (broker 用 order_no 回报)
    4. ack.code==0: UPDATE status=50 + broker_order_id + ws push
    5. ack.code!=0: UPDATE status=57 + cancelled_volume=volume + ws push
    6. 异常 (RPC 超时/broker down): UPDATE status=57 + ws push (status_msg 携带异常)
    7. log.exception 永远记 (异常吞掉是最大风险, 必须留 trace)

    关键: 全程 try/except 包裹, 任何路径都不允许吞掉异常.
    """
    log = logging.getLogger(__name__)
    # 关键: task 内 late import 取 module-level ord_stk/ws_manager (monkeypatch 兼容)
    from server.api.orders import ord_stk, ws_manager
    from server.services.push.helpers import _order_to_out_dict

    try:
        # v81 tables-migration: Orders.query_one (复合 PK) 替代 db.query(Order).filter_by(...).first()
        order = Orders.query_one(trd_date=trd_date, order_no=order_no)
        if not order:
            log.error("_submit_rpc_async: trd_date=%s order_no=%s not found", trd_date, order_no)
            return

        # 5. 调 RPC
        try:
            ack = await ord_stk(
                stock_code=order.stock_code, order_type=order.order_type,
                price_type=order.price_type, price=order.price, volume=order.volume,
                remark=order.order_no,
            )
        except Exception as e:
            log.exception("place_order RPC failed: stock=%s order_no=%s", order.stock_code, order_no)
            order.status = "57"  # broker JUNK 废单
            order.status_msg = "RPC 失败: {}".format(e)
            # v81 tables-migration: obj.update(Orders, pk=...) 替代 db.commit() + db.refresh()
            order.update(Orders, trd_date=trd_date, order_no=order_no)
            try:
                asyncio.ensure_future(ws_manager.broadcast("order_update", _order_to_out_dict(order)))
            except Exception as push_err:
                log.warning("ws push (RPC exception path) failed: %s", push_err)
            return

        # 6. 解析 ack
        ack_code = int(ack.get("code", -1))
        ack_list = ack.get("list", [])
        broker_order_id = ""
        if ack_code == 0 and ack_list and isinstance(ack_list[0], dict):
            broker_order_id = str(ack_list[0].get("order_id", ""))
            if broker_order_id:
                order.order_id = broker_order_id
            order.status = "50"  # broker REPORTED 已报 (v11)
            order.status_msg = "已报"
        else:
            order.status = "57"  # broker JUNK 废单 (v11)
            order.status_msg = ack.get("msg", "柜台拒单")
            # R2a 本地拒单时把 cancelled_volume 抹平到 volume
            order.cancelled_volume = order.volume
        print(f"RPC_DONE: ack_code={ack_code} broker_order_id={broker_order_id} set_status={order.status}", flush=True)
        # v81 tables-migration: 单次 update_one 替代 db.commit() + db.refresh()
        order.update(Orders, trd_date=trd_date, order_no=order_no)

        # 7. ws push 阶段 B 结果
        try:
            asyncio.ensure_future(ws_manager.broadcast("order_update", _order_to_out_dict(order)))
        except Exception as e:
            log.warning("ws push (RPC done) failed: %s", e)

    except Exception as e:
        # 任何意外 (DB 查询失败/提交失败等) 也必须 log, 不允许吞掉
        log.exception("_submit_rpc_async top-level error: order_no=%s err=%s", order_no, e)
