"""
push_handlers.py — v4 推送落库

监听 4 类 push 事件，把柜台主动推送写/更新到本地 SQLite：
  - ord_cfm: 委托状态/成交通知（首次报单、状态变化）
  - trd_cfm: 成交回报
  - pos_cfm: 持仓变化
  - ast_cfm: 资金变化

字段映射规则：
  - ord_cfm: 用 order_remark 匹配本地 Order（因为我们下单时把 order_no 作为 remark 传给柜台）
  - trd_cfm: 用 order_id 匹配本地 Order
  - pos_cfm: 整张持仓表快照覆盖
  - ast_cfm: 整行资产表覆盖
"""
from datetime import datetime
from sqlalchemy import text
from typing import Dict, Any
from sqlalchemy.orm import Session

from models.orm import (
    Order, Trade, Position, Asset, TradingDay,
)


# 状态码映射（与柜台一致）
ORDER_STATUS = {
    "48": "已报待确认",
    "49": "已报",
    "50": "部成",
    "51": "已成",
    "52": "部撤",
    "53": "已撤",
    "54": "已撤单",
    "55": "废单",
    "56": "部成已撤",
}


def _get_active_trd_date(db: Session) -> str:
    """获取当前激活交易日；未激活则用 MAX(TRD_DATE)"""
    row = db.query(TradingDay).filter_by(status='active').first()
    if row:
        return row.current_date
    for table in ("orders", "trades", "positions", "assets"):
        r = db.execute(text(f"SELECT MAX(TRD_DATE) FROM {table}")).first()
        if r and r[0]:
            return r[0]
    return datetime.now().strftime('%Y%m%d')


def _str(v: Any, default: str = '') -> str:
    """安全取字符串值"""
    if v is None:
        return default
    return str(v)


def _float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


# ───── ord_cfm：委托确认 ─────

def handle_ord_cfm(db: Session, row: Dict[str, Any], ts: str) -> None:
    """处理 ord_cfm 推送

    柜台字段（举例）：
      order_id       柜台委托号
      order_remark   委托备注（即我们下传的本地的 order_no）
      stock_code
      order_type
      price_type
      price
      volume
      traded_volume
      traded_amount
      avg_price
      status         48/49/50/51/52/53/55
      status_msg
    """
    broker_order_id = _str(row.get('order_id', ''))
    order_remark = _str(row.get('order_remark', ''))
    status = _str(row.get('status', ''))

    if not broker_order_id and not order_remark:
        print(f"[ord_cfm] skip: no order_id and no order_remark")
        return

    # 优先用 broker_order_id 精确匹配；否则用 order_remark (我们下传的 order_no)
    order = None
    if broker_order_id:
        order = db.query(Order).filter_by(order_id=broker_order_id).first()
    if not order and order_remark:
        order = db.query(Order).filter_by(order_remark=order_remark).first()

    if not order:
        # 极端情况：push 来了但本地没有（重启后丢单）
        # 不创建新单（避免错位），只打日志
        print(f"[ord_cfm] WARN: no local order for order_id={broker_order_id} remark={order_remark}")
        return

    # 更新字段
    if broker_order_id and order.order_id != broker_order_id:
        order.order_id = broker_order_id
    if status:
        order.status = status
        order.status_msg = _str(row.get('status_msg', ''))
    order.traded_volume = _int(row.get('traded_volume', order.traded_volume))
    order.traded_amount = _float(row.get('traded_amount', order.traded_amount))
    order.avg_price = _float(row.get('avg_price', order.avg_price))
    if _str(row.get('price', '')):
        order.price = _float(row.get('price', order.price))
    if _str(row.get('volume', '')):
        order.volume = _int(row.get('volume', order.volume))
    order.pushed_at = datetime.utcnow()
    order.updated_at = datetime.utcnow()

    print(f"[ord_cfm] updated order_id={order.order_id} status={order.status} traded={order.traded_volume}")


# ───── trd_cfm：成交回报 ─────

def handle_trd_cfm(db: Session, row: Dict[str, Any], ts: str) -> None:
    """处理 trd_cfm 推送（每笔成交）

    柜台字段（举例）：
      trade_id       成交编号（UNIQUE）
      order_id       关联委托号
      stock_code
      order_type     23=买 24=卖
      price          成交价
      volume         成交量
      amount         成交额
      trade_time     成交时间
    """
    trade_id = _str(row.get('trade_id', ''))
    if not trade_id:
        # 用 order_id + trade_time 作 fallback key
        trade_id = f"{row.get('order_id', '')}-{row.get('trade_time', '')}"

    # 幂等：已存在则不重复插入
    existing = db.query(Trade).filter_by(trade_id=trade_id).first()
    if existing:
        return

    broker_order_id = _str(row.get('order_id', ''))
    # 找本地 Order（同步更新累计）
    order = db.query(Order).filter_by(order_id=broker_order_id).first() if broker_order_id else None

    trd = _str(row.get('trade_date', '')) or _get_active_trd_date(db)
    if not trd or len(trd) != 8:
        trd = _get_active_trd_date(db)

    trade = Trade(
        trade_id=trade_id,
        TRD_DATE=trd,
        order_id=broker_order_id,
        stock_code=_str(row.get('stock_code', '')),
        order_type=_str(row.get('order_type', '')),
        price=_float(row.get('price', 0)),
        volume=_int(row.get('volume', 0)),
        amount=_float(row.get('amount', 0)),
        trade_time=_str(row.get('trade_time', ts)),
    )
    db.add(trade)
    db.flush()

    # 同步更新 Order 累计
    if order:
        order.traded_volume = (order.traded_volume or 0) + trade.volume
        order.traded_amount = (order.traded_amount or 0) + trade.amount
        if trade.price and trade.volume:
            order.avg_price = order.traded_amount / order.traded_volume
        order.pushed_at = datetime.utcnow()
        order.updated_at = datetime.utcnow()

    print(f"[trd_cfm] inserted trade_id={trade_id} order_id={broker_order_id} vol={trade.volume} px={trade.price}")


# ───── pos_cfm：持仓变化（整表快照） ─────

def handle_pos_cfm(db: Session, row: Dict[str, Any], ts: str) -> None:
    """处理 pos_cfm 推送

    柜台字段（单条持仓）：
      stock_code
      volume         持仓数量
      available      可用数量
      cost_price     成本价
      market_value   市值
      TRD_DATE
    """
    stock_code = _str(row.get('stock_code', ''))
    if not stock_code:
        return
    trd = _str(row.get('TRD_DATE', '')) or _get_active_trd_date(db)
    if len(trd) != 8:
        trd = _get_active_trd_date(db)

    pos = db.query(Position).filter_by(
        TRD_DATE=trd, stock_code=stock_code
    ).first()

    if not pos:
        pos = Position(TRD_DATE=trd, stock_code=stock_code)
        db.add(pos)

    pos.total = _int(row.get('volume', 0))
    pos.available = _int(row.get('available', pos.total))
    pos.cost = _float(row.get('cost_price', row.get('cost', 0)))
    # market_value 由前端根据行情实时计算，后端不存储
    pos.synced_at = datetime.utcnow()
    pos.synced_from = 'push_pos_cfm'

    print(f"[pos_cfm] updated {stock_code} vol={pos.total} cost={pos.cost}")


# ───── ast_cfm：资金变化（单行覆盖） ─────

def handle_ast_cfm(db: Session, row: Dict[str, Any], ts: str) -> None:
    """处理 ast_cfm 推送

    柜台字段（资金账户）：
      total_asset    总资产
      cash           现金
      frozen         冻结
      market_value   持仓市值
      available      可用
      TRD_DATE
    """
    trd = _str(row.get('TRD_DATE', '')) or _get_active_trd_date(db)
    if len(trd) != 8:
        trd = _get_active_trd_date(db)

    asset = db.query(Asset).filter_by(TRD_DATE=trd).first()
    if not asset:
        asset = Asset(TRD_DATE=trd)
        db.add(asset)

    asset.total_asset = _float(row.get('total_asset', 0))
    asset.cash = _float(row.get('cash', 0))
    asset.frozen_cash = _float(row.get('frozen', 0))
    asset.market_value = _float(row.get('market_value', 0))
    asset.synced_at = datetime.utcnow()
    asset.synced_from = 'push_ast_cfm'

    print(f"[ast_cfm] updated total={asset.total_asset} cash={asset.cash}")


# ───── 路由 ─────

HANDLERS = {
    "ord_cfm": handle_ord_cfm,
    "trd_cfm": handle_trd_cfm,
    "pos_cfm": handle_pos_cfm,
    "ast_cfm": handle_ast_cfm,
}


def handle_push(db: Session, func: str, row: Dict[str, Any], ts: str) -> None:
    """统一入口"""
    handler = HANDLERS.get(func)
    if not handler:
        return
    handler(db, row, ts)
