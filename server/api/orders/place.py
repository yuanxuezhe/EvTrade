"""
place.py — POST /api/orders/place 下单端点

两阶段下单架构 (REQ-TRADE-028):
- 阶段 A: DB INSERT status=48 未报 → ws push + 立即 HTTP 应答 (含 status=48 OrderOut)
- 阶段 B: RPC 后台 task → DB UPDATE status=50/57 + ws push
  - RPC 成功 (ack.code==0): UPDATE status=50 + 写 broker_order_id + ws push
  - RPC 失败 (ack.code!=0): UPDATE status=57 + cancelled_volume=volume + ws push
  - RPC 异常 (timeout/broker down): UPDATE status=57 + ws push (status_msg="RPC 超时/异常: ...")

设计意图:
- DB INSERT → ws push status=48 → 立即 HTTP 应答. RPC 后台 fire-and-forget.
  - 前端拿到 status=48 立即渲染 "待回报"; ws 后续推 status=50/57 覆盖
  - broker 慢/超时不影响 HTTP 应答 (axios 15s timeout 仍兜底)
  - RPC 异常吞掉会丢委托, 必须 try/except + ws push + log.exception

- DB I/O 全部走 server.tables.* (Orders.add_one / Orders.query_one / Orders.update_one / T0Tasks.query_one)
- 交易日走 server.repo.orders._get_active_trd_date (tables 层)
- 插入 + 更新为 Row 风格: obj.x = val; obj.update(Orders, **pk)

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
from server.api.deps import require_rpc_ok  # RPC 健康统一 deps
from server.repo.orders import (
    _get_active_trd_date,
    insert_pending_order,
    next_order_no,
)
from server.utils.time import format_ts
from server.services.t0 import calc_net_amount, calc_t0_volume, get_fee_config
from server.repo.stocks import GetStockInfo  # 统一证券信息入口
from server.services.sysconfig import get_cantrd_stktypes
from server.tables import Orders, T0Tasks
from server.api.orders.schemas import (
    PlaceOrderRequest,
    PlaceOrderResponse,
    _to_order_out,
)

log = logging.getLogger(__name__)


def register_place(router):
    """注册 POST /place 端点到 FastAPI router。"""

    @router.post("/place", response_model=PlaceOrderResponse,
                 dependencies=[Depends(require_trader), Depends(require_trading_day),
                               Depends(require_trading_session),
                               Depends(require_rpc_ok)])
    async def place_order(req: PlaceOrderRequest, user: User = Depends(get_current_user)):
        """下单（两阶段：DB 写入立即应答，RPC 后台异步回报）

        全部走 server.tables.*
        """
        # Late import 拿 patched symbol（test_orders_api.py monkeypatch 路径）
        from server.api.orders import ord_stk, ws_manager

        if req.order_type not in ("23", "24"):
            raise HTTPException(status_code=400, detail={"code": "BAD_ORDER_TYPE", "msg": "order_type 必须 23(买) 24(卖)"})

        # RPC 健康检查已通过 Depends(require_rpc_ok) 在路由层拦截

        # stktype 可交易校验 + 价格按 stock.scale 四舍五入
        # 用 GetStockInfo() 一次性拿 stktype + scale
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

        # 1. 取交易日 + order_no（幂等由 order_no 单调递增保证）
        #    SysStatus 单行 (id=1), 走 repo helper
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

        # 3.5 若带 task_id, 验证 task 归属 + active (避免跨用户误绑定)
        #    T0Tasks.query_one(id=...)
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
        #    走 insert_pending_order (Orders.add_one 封装), 返回 Row
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
        # 补全 task_id + strategy_type (insert_pending_order 通用, 不含这俩)
        #   母单路径: signal_consumer 传 req.task_id=strategy_order.task_id,
        #   req.strategy_type=2 (signal_consumer 已校验 parent_task_id 非空).
        if req.task_id is not None or req.strategy_type:
            order.task_id = req.task_id
            order.strategy_type = req.strategy_type
            order.update(Orders, trd_date=trd_date, order_no=order_no)

        # 5. 阶段 A — 立即 ws push status=48 (前端立即显示 "待报")
        #   走统一 _broadcast_order_cfm helper (包装 type='ord_cfm' + channel + data),
        #          与 push/dispatcher.py 推送同协议, 前端 ws_dispatch 才能识别.
        from server.services.push.order_broadcast import _broadcast_order_cfm as _oc_broadcast
        try:
            _oc_broadcast(order, trace_id=order_no)
        except Exception as e:
            log.warning("ws push (status=48) failed: %s", e)

        # 6. 阶段 B — RPC 后台 task (fire-and-forget)
        #   asyncio.create_task 不会阻塞 HTTP 应答; broker 慢/超时不影响前端.
        #   关键: task 内 late import 拿 patched ord_stk/ws_manager (test_orders_api.py monkeypatch).
        #   trd_date/order_no 捕获到闭包 (闭包避免 Row detached 问题).
        #   注: Orders 表 (trd_date, order_no) 联合 PK 定位
        _captured_trd_date = trd_date
        asyncio.create_task(_submit_rpc_async(order_no, _captured_trd_date))

        # 7. 立即 HTTP 应答 (含 status=48 OrderOut)
        #   code=0 表示"DB 写入成功, RPC 已调度" (此时代码=48 委托还未被 broker 确认)
        #   msg 明确告知前端 "DB 已写入, broker 回报中" 区别于 code=1 broker 拒单.
        return PlaceOrderResponse(
            code=0, msg="DB 已写入, broker 回报中 (异步模式)",
            order=_to_order_out(order),
            list=[_to_order_out(order)],
            broker_order_id="",  # broker 回报后由 _submit_rpc_async 写入, 后续 ws push 推送
            fee_breakdown={"gross": gross, "net": net, "commission_rate": fee_cfg["commission_rate"]},
            t0_adjusted_volume=adjusted,
        )


async def _submit_rpc_async(order_no: str, trd_date: str):
    """
    RPC 异步执行函数 (阶段 B 后台 task)

    关键机制:
      - 下单时传 msgid_meta (order_no + trd_date + stock_code), 让 transport._MSGID_ORDERNO_CACHE
        按 msgid 注册. 应答到达时按 msgid 反查 → 异步废单.
      - code == 0: 不处理 (broker ord_cfm push 会异步推真实 broker_order_id + status=50).
        应答包中 broker_order_id 此时空, 真正的 broker_order_id 在 broker 异步推送的 ord_cfm 包里才有.
      - code != 0: 也不在 place.py 处理, 由 transport 层 _handle_ord_stk_reply_junk 接管.
        因为 cache 已注册, transport 按 msgid 反查 → 异步废单 + status_msg + ws push.
      - RPC 异常 (publish/wait_for 超时): 兜底写 status=57 + msg (transport cache 已 evict).
      - ord_cfm / trd_cfm push: 由 handle_ord_cfm / handle_trd_cfm 处理真实 broker 状态.

    流程:
      1. Orders.query_one (自带引擎)
      2. late import 拿 patched ord_stk/ws_manager (monkeypatch 测试兼容)
      3. 调 broker ord_stk, 传 msgid_meta
      4. ack 已收到: 不写 Order (transport 接管 code!=0; code==0 由 ord_cfm 推)
      5. 异常: 兜底写 status=57 + msg
      6. log.exception 永远记
    """
    log = logging.getLogger(__name__)
    # 关键: task 内 late import 取 module-level ord_stk/ws_manager (monkeypatch 兼容)
    from server.api.orders import ord_stk, ws_manager
    from server.services.push.order_broadcast import _broadcast_order_cfm

    try:
        # Orders.query_one (复合 PK)
        order = Orders.query_one(trd_date=trd_date, order_no=order_no)
        if not order:
            log.error("_submit_rpc_async: trd_date=%s order_no=%s not found", trd_date, order_no)
            return

        # 构建 msgid_meta 让 transport._handle_reply 按 msgid 接管废单路径
        msgid_meta = {
            "order_no": order.order_no,
            "trd_date": trd_date,
            "stock_code": order.stock_code or "",
        }

        # 5. 调 RPC
        try:
            ack = await ord_stk(
                stock_code=order.stock_code, order_type=order.order_type,
                price_type=order.price_type, price=order.price, volume=order.volume,
                remark=order.order_no,
                msgid_meta=msgid_meta,
            )
        except Exception as e:
            log.exception("place_order RPC failed: stock=%s order_no=%s", order.stock_code, order_no)
            # transport cache 已被 _evict_msgid_orderno 清掉 (call() 超时路径),
            # 这里必须兜底写废单 (否则订单卡在 status=48)
            order.status = "57"  # broker JUNK 废单
            order.status_msg = "RPC 失败: {}".format(e)
            order.update(Orders, trd_date=trd_date, order_no=order_no)
            try:
                _broadcast_order_cfm(order, trace_id=order_no)
            except Exception as push_err:
                log.warning("ws push (RPC exception path) failed: %s", push_err)
            return

        # 不解 ack.code, 不写 Order (broker ord_cfm push 会异步处理真实状态)
        #      transport._handle_ord_stk_reply_junk 已在另一个线程处理了 code!=0 废单路径
        #      code==0 应答: broker_order_id 此时空, ord_cfm 异步推来时才有
        try:
            ack_code = int(ack.get("code", -1)) if isinstance(ack, dict) else -1
        except (TypeError, ValueError):
            ack_code = -1
        log.info(
            "_submit_rpc_async: order_no=%s ack received (code=%s). " +
            "code=0 → wait broker ord_cfm push; code!=0 → transport cache write handled.",
            order_no, ack_code,
        )

    except Exception as e:
        # 任何意外 (DB 查询失败/提交失败等) 也必须 log, 不允许吞掉
        log.exception("_submit_rpc_async top-level error: order_no=%s err=%s", order_no, e)
