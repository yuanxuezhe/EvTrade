"""
push_handler_trd.py — trd_cfm 处理（v7: Trade PK = (trd_date, order_no, trade_id)）

行为：
- 用 broker.remark（= 本地 order_no）匹配本地 Order
- Trade 幂等插入：PK 存在则跳过
- 同步更新 Order traded_volume / traded_amount / avg_price
- 用 _infer_order_status 本地推断 status（不传 broker_status，trd_cfm 永远不写撤单类）
"""
from typing import Any, Dict

from sqlalchemy.orm import Session

from server.models.orm import Order, Trade
from server.services.order_status import _get_active_trd_date, _infer_order_status, _status_msg
from server.services.push_helpers import _float, _int, _str, _utcnow


def handle_trd_cfm(db: Session, row: Dict[str, Any], ts: str) -> None:
    """处理 trd_cfm 推送（v7: Trade 用 order_no 入 PK，不写 order_id）

    柜台字段（举例）：
      trade_id       成交编号(UNIQUE,去重用)
      order_id       关联委托号(v7 仅作 Order 兜底查找用，不再写 Trade)
      remark         委托备注(= 本地 order_no,v7 写入 Trade.order_no 入 PK)
      stock_code
      order_type     23=买 24=卖
      price          成交价
      volume         成交量
      amount         成交额
      trade_time     成交时间
    """
    trd_date = _str(row.get('trade_date', '')) or _get_active_trd_date(db)
    if not trd_date or len(trd_date) != 8:
        trd_date = _get_active_trd_date(db)

    broker_order_id = _str(row.get('order_id', ''))
    broker_remark = _str(row.get('remark', ''))  # v7: 本地 order_no

    # v7: order_no 是 Trade PK 第二段,缺则不写孤儿 Trade
    if not broker_remark:
        print("[trd_cfm] WARN: no order_no (remark 缺失),跳过 trade_id={}".format(
            row.get('trade_id', '')))
        return

    trade_id = _str(row.get('trade_id', ''))
    if not trade_id:
        # v7: 用 order_no + trade_time 作 fallback key（替代原 order_id + trade_time）
        trade_id = "{}-{}".format(broker_remark, row.get('trade_time', ''))

    # 幂等:已存在则不重复插入(PK = (trd_date, order_no, trade_id))
    existing = db.query(Trade).filter_by(
        trd_date=trd_date, order_no=broker_remark, trade_id=trade_id
    ).first()
    if existing:
        return

    # v7: 优先用 remark (= 本地 order_no) 查 Order,broker order_id 只作兜底
    order = db.query(Order).filter_by(order_no=broker_remark, trd_date=trd_date).first()
    if not order and broker_order_id:
        order = db.query(Order).filter_by(order_id=broker_order_id, trd_date=trd_date).first()

    trade = Trade(
        trd_date=trd_date,
        order_no=broker_remark,
        trade_id=trade_id,
        stock_code=_str(row.get('stock_code', '')),
        order_type=_str(row.get('order_type', '')),
        price=_float(row.get('price', 0)),
        volume=_int(row.get('volume', 0)),
        amount=_float(row.get('amount', 0)),
        trade_time=_str(row.get('trade_time', ts)),
    )
    db.add(trade)
    db.flush()

    # 同步更新 Order 累计 + 推断 status
    if order:
        order.traded_volume = (order.traded_volume or 0) + trade.volume
        order.traded_amount = (order.traded_amount or 0) + trade.amount
        if trade.price and trade.volume:
            order.avg_price = order.traded_amount / order.traded_volume
        # v6: 累计后本地推断 status(不传 broker_status,trd_cfm 永远不写撤单类状态)
        order.status = _infer_order_status(order)
        order.status_msg = _status_msg(order.status)
        order.pushed_at = _utcnow()
        order.updated_at = _utcnow()
    else:
        print("[trd_cfm] WARN: no order for trade_id={} (order_no={}, order_id={}) — Trade 行已留存".format(
            trade_id, broker_remark, broker_order_id))

    print("[trd_cfm] inserted trade_id={} order_no={} vol={} px={} order_status={}".format(
        trade_id, broker_remark, trade.volume, trade.price,
        order.status if order else 'N/A'))
