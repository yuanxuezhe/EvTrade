"""
push_handlers.py — v6 推送落库（order-pk-by-orderno）

监听 4 类 push 事件，把柜台主动推送写/更新到本地 SQLite：
  - ord_cfm: 委托状态/成交通知（首次报单、状态变化）
  - trd_cfm: 成交回报
  - pos_cfm: 持仓变化
  - ast_cfm: 资金变化

字段映射规则（v6）：
  - ord_cfm: 用 broker.remark（= 本地 order_no）匹配本地 Order，写入 order_id
  - trd_cfm: 同样用 broker.remark（= 本地 order_no）匹配本地 Order，累加 traded_*
  - 委托 status 字段统一由 _infer_order_status 本地推断（不再直接抄 broker 推的 status）
  - pos_cfm: 按 stock_code UPSERT（positions 表无 trd_date）
  - ast_cfm: 单行资产表覆盖
"""
from datetime import datetime, timezone
import logging
from sqlalchemy import text
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session

from models.orm import (
    Order, Trade, Position, Asset, SysStatus,
)

log = logging.getLogger(__name__)

def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# 状态码映射（与柜台一致,本地文字描述）
ORDER_STATUS = {
    "48": "待报",
    "49": "已报",
    "50": "部成",
    "51": "已成",
    "52": "部撤",
    "53": "已撤",
    "54": "已撤单",
    "55": "废单",
    "56": "部成部撤",
}

# 终态:trd_cfm 累计推断时不再覆盖（避免 broker 撤单后又推 trd_cfm 把 status 改回 50）
TERMINAL_STATUSES = ('51', '52', '53', '54', '55', '56')


def _status_msg(status: str) -> str:
    """状态码 → 本地文字"""
    return ORDER_STATUS.get(status, '')


def _infer_order_status(order: Order, broker_status: Optional[str] = None) -> str:
    """委托 status 本地推断

    Args:
        order: Order 实例,需要 traded_volume / volume / status(当前值) 字段
        broker_status: 可选,broker ord_cfm 推的 status 字段(52/53/54 视为撤单类)
                     trd_cfm 调用时传 None(trd_cfm 永远不写撤单类状态)

    Returns:
        推断后的 status: 49 / 50 / 51 / 53 / 56

    规则:
      1. 当前 status 已是终态(51/52/53/54/55/56) → 保持,不再推断
         (避免 trd_cfm 累计覆盖 ord_cfm 写的撤单终态)
      2. broker_status 给出且在 (52, 53, 54) → 撤单类
         - cumulative = 0           → 53 (已撤)
         - 0 < cumulative < volume  → 56 (部成部撤)
         - cumulative = volume      → 51 (已成,broker 推撤单但已全成)
      3. 累计推断
         - cumulative = 0           → 49 (已报)
         - 0 < cumulative < volume  → 50 (部成)
         - cumulative = volume      → 51 (已成)
    """
    current = order.status or '48'

    # 1. 终态保持
    if current in TERMINAL_STATUSES:
        return current

    cum = order.traded_volume or 0
    vol = order.volume or 0

    # 2. broker 推了撤单类 status
    if broker_status and broker_status in ('52', '53', '54'):
        if cum == 0:
            return '53'
        if cum < vol:
            return '56'
        return '51'  # 已成,broker 撤单无意义

    # 3. 累计推断
    if cum == 0:
        return '49'
    if cum < vol:
        return '50'
    return '51'


def _get_active_trd_date(db: Session) -> str:
    """获取当前激活交易日；未激活则用 MAX(trd_date)"""
    row = db.query(SysStatus).filter_by(status='active').first()
    if row:
        return row.trd_date
    for table in ("orders", "trades", "positions", "reconcile_report"):
        r = db.execute(text(f"SELECT MAX(trd_date) FROM {table}")).first()
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
        print(f"[ord_cfm] skip: no order_id and no remark")
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
        print(f"[ord_cfm] WARN: no local order for order_id={broker_order_id} remark={broker_remark}")
        return

    # v6: 不再有 PENDING- 占位,broker order_id 直接写入(覆盖 NULL)
    if broker_order_id and order.order_id != broker_order_id:
        order.order_id = broker_order_id

    # 委托 status 由 _infer_order_status 本地推断
    # (broker_status 临时喂进去:52/53/54 视为撤单类信号)
    order.status = _infer_order_status(order, broker_status=broker_status or None)
    order.status_msg = _str(row.get('status_msg', '')) or _status_msg(order.status)
    order.pushed_at = _utcnow()
    order.updated_at = _utcnow()

    print(f"[ord_cfm] updated order_no={order.order_no} order_id={order.order_id} status={order.status} (broker_status={broker_status}, cum={order.traded_volume}/{order.volume})")


# ───── trd_cfm：成交回报 ─────

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
        print(f"[trd_cfm] WARN: no order_no (remark 缺失),跳过 trade_id={row.get('trade_id', '')}")
        return

    trade_id = _str(row.get('trade_id', ''))
    if not trade_id:
        # v7: 用 order_no + trade_time 作 fallback key（替代原 order_id + trade_time）
        trade_id = f"{broker_remark}-{row.get('trade_time', '')}"

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
        print(f"[trd_cfm] WARN: no order for trade_id={trade_id} (order_no={broker_remark}, order_id={broker_order_id}) — Trade 行已留存")

    print(f"[trd_cfm] inserted trade_id={trade_id} order_no={broker_remark} vol={trade.volume} px={trade.price} order_status={order.status if order else 'N/A'}")


# ───── pos_cfm：持仓变化（单股 UPSERT） ─────

def handle_pos_cfm(db: Session, row: Dict[str, Any], ts: str) -> None:
    """处理 pos_cfm 推送

    柜台字段（单条持仓）：
      stock_code
      volume         持仓数量（broker 实际可能不送,只送 available）
      available      可用数量
      cost_price     成本价
      market_value   市值

    字段映射（v6,2026-06-16 引入 vol 兜底）：
      vol     ← row.volume        (缺字段或为 0 时兜底为 avl_vol)
      avl_vol ← row.available
      cost    ← row.cost_price
      last_vol / today_buy / today_sell 由对账时设置（push 单次无法判定）
      market_value 由前端根据行情实时计算,后端不存储
    """
    stock_code = _str(row.get('stock_code', ''))
    if not stock_code:
        return

    pos = db.query(Position).filter_by(stock_code=stock_code).first()
    if not pos:
        pos = Position(stock_code=stock_code)
        db.add(pos)

    avl = _int(row.get('available', 0))
    pos.avl_vol = avl
    # 兜底:broker 实际生产中 pos_cfm 行常只送 available 不送 volume
    # 此时用 avl_vol 兜底,确保 PositionTable 总持仓列有值
    vol_val = _int(row.get('volume', 0))
    pos.vol = vol_val if vol_val > 0 else avl
    pos.cost_price = _float(row.get('cost_price', row.get('cost', 0)))
    pos.synced_at = _utcnow()
    pos.synced_from = 'push_pos_cfm'

    # 异常时（broker 推的 vol 与 avl 不一致）打 info,便于排查
    if vol_val > 0 and vol_val != avl:
        print(f"[pos_cfm] {stock_code} vol={vol_val} != avl={avl} (broker 正常情形)")

    print(f"[pos_cfm] updated {stock_code} vol={pos.vol} cost={pos.cost_price}")


# ───── ast_cfm：资金变化（单行覆盖） ─────

def handle_ast_cfm(db: Session, row: Dict[str, Any], ts: str) -> None:
    """处理 ast_cfm 推送

    柜台字段（资金账户）：
      total_asset    总资产
      cash           现金
      frozen         冻结
      market_value   持仓市值
      available      可用
    """
    asset = db.query(Asset).first()
    if not asset:
        asset = Asset()
        db.add(asset)

    asset.total_asset = _float(row.get('total_asset', 0))
    asset.cash = _float(row.get('cash', 0))
    asset.frozen_cash = _float(row.get('frozen', 0))
    asset.market_value = _float(row.get('market_value', 0))
    asset.synced_at = _utcnow()
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
        # v7 改: 缺 handler 不再静默 return, 方便 broker 加新 func 时能被定位
        log.warning("handle_push: unknown func=%r row=%r ts=%s", func, row, ts)
        return
    handler(db, row, ts)
