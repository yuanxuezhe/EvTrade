"""
push_handler_pos.py — pos_cfm 处理（单股 UPSERT）

行为：
- 按 stock_code 查找本地 Position，不存在则新建
- 写入 avl_vol / vol（broker 不送 volume 时用 avl_vol 兜底）/ cost_price
- market_value 由前端根据行情实时计算,后端不存储
"""
from typing import Any, Dict

from sqlalchemy.orm import Session

from server.models.orm import Position
from server.services.push_helpers import _float, _int, _str, _utcnow


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
        print("[pos_cfm] {} vol={} != avl={} (broker 正常情形)".format(
            stock_code, vol_val, avl))

    print("[pos_cfm] updated {} vol={} cost={}".format(
        stock_code, pos.vol, pos.cost_price))
