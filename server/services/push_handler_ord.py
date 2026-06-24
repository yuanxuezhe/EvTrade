"""
push_handler_ord.py — ord_cfm 处理（v6: 只填 order_id + 推断 status）

行为：
- 用 broker.remark（= 本地 order_no）匹配本地 Order
- 写入 broker_order_id
- 累加 cancelled_volume（兼容 cancelled_volume / cancel_volume / withdrawn_volume 字段名）
- 用 _infer_order_status 本地推断 status（不直接抄 broker）
"""
from typing import Any, Dict

from sqlalchemy.orm import Session

from server.models.orm import Order
from server.services.order_status import _infer_order_status, _status_msg
from server.services.push_helpers import _int, _str, _utcnow


def handle_ord_cfm(db: Session, row: Dict[str, Any], ts: str) -> None:
    """处理 ord_cfm 推送（v6: 简化为只填 order_id + 推断 status）

    柜台字段（举例）：
      order_id       柜台委托号
      remark         委托备注（即我们下传的本地的 order_no）
      stock_code
      order_type
      price_type
      price
      volume
      status         48/49/50/51/52/53/55 — 临时喂给 _infer_order_status，不直接写
      status_msg
    """
    broker_order_id = _str(row.get('order_id', ''))
    broker_remark = _str(row.get('remark', ''))  # ← broker 透传回来的 order_no
    broker_status = _str(row.get('status', ''))

    if not broker_order_id and not broker_remark:
        print("[ord_cfm] skip: no order_id and no remark")
        return

    # 用 broker.remark (= 我们下传的 order_no) 匹配本地 Order
    order = None
    if broker_remark:
        order = db.query(Order).filter_by(order_no=broker_remark).first()
    if not order and broker_order_id:
        # 兜底:broker 没送 remark 时按 order_id 查
        order = db.query(Order).filter_by(order_id=broker_order_id).first()

    if not order:
        # 极端情况:push 来了但本地没有(重启后丢单)
        # 不创建新单(避免错位),只打日志
        print("[ord_cfm] WARN: no local order for order_id={} remark={}".format(
            broker_order_id, broker_remark))
        return

    # v6: 不再有 PENDING- 占位,broker order_id 直接写入(覆盖 NULL)
    if broker_order_id and order.order_id != broker_order_id:
        order.order_id = broker_order_id

    # v8: 累加 cancelled_volume(broker 不同版本字段名兼容)
    cancelled = (_int(row.get('cancelled_volume', None), 0)
                 or _int(row.get('cancel_volume', None), 0)
                 or _int(row.get('withdrawn_volume', None), 0))
    if cancelled > 0:
        # 累加(避免 broker 重推时丢数)
        new_cancelled = (order.cancelled_volume or 0) + cancelled
        # 不超过委托数
        if order.volume and new_cancelled > order.volume:
            new_cancelled = order.volume
        order.cancelled_volume = new_cancelled

    # 委托 status 由 _infer_order_status 本地推断
    # (broker_status 临时喂进去:52/53/54 视为撤单类信号)
    order.status = _infer_order_status(order, broker_status=broker_status or None)
    order.status_msg = _str(row.get('status_msg', '')) or _status_msg(order.status)
    order.pushed_at = _utcnow()
    order.updated_at = _utcnow()

    print("[ord_cfm] updated order_no={} order_id={} status={} (broker_status={}, cum={}/{})".format(
        order.order_no, order.order_id, order.status, broker_status,
        order.traded_volume, order.volume))
