"""
push/pos.py — v118 pos_push 处理

broker 端 position_callback 推送 pos_push 事件 (xtquant 协议):
  stock_code, last_vol, vol, avl_vol, avg_price

设计 (v118 后):
  - pos_push 是持仓数据的唯一权威源
  - trd_cfm 不再处理持仓 (仅写 trades + orders)
  - reconcile 不再覆盖持仓 (仅初始化时用 qry_positions 同步)

行为:
  - upsert Position 行 (broker 推的是最新快照, 直接覆盖)
  - 返回 PositionOut dict 给 dispatcher 广播 position_update
  - 2026-07-31: 4 业务字段 (last_vol/vol/avl_vol/cost_price) 与 DB 全等时
    直接返回 None, dispatcher 跳过 WS 广播, 避免 broker 重连/心跳产生的
    无效 DB 写 + 前端 cache 抖动 (REQ-PUSH-034)
"""
from typing import Any, Dict, Optional

from server.tables import Positions
from server.utils.time import _utcnow
from server.services.push.helpers import _int, _float, _str, _position_to_out_dict

# REQ-PUSH-034: 参与 diff 判断的 4 个持仓业务字段
# 与 REQ-PUSH-031 (trd_cfm 增量作用域) 保持一致
_POS_DIFF_FIELDS = ('last_vol', 'vol', 'avl_vol', 'cost_price')


def _fields_unchanged(existing_pos, incoming: Dict[str, Any]) -> bool:
    """REQ-PUSH-034: 比对 4 业务字段, 全等返回 True.

    Args:
        existing_pos: ORM Row 或 None (None → 视为变化, 走 add_one 路径)
        incoming: dict 含 last_vol/vol/avl_vol/cost_price

    Returns:
        True iff 4 字段全部相等 (且 existing_pos 非 None)
    """
    if existing_pos is None:
        return False
    for field in _POS_DIFF_FIELDS:
        incoming_val = incoming.get(field)
        existing_val = getattr(existing_pos, field, None)
        # float 字段 (cost_price) 直接 == 比对, broker 推的是固定精度数值
        if existing_val != incoming_val:
            return False
    return True


def handle_pos_push(db, row: Dict[str, Any], ts: str) -> Optional[Dict[str, Any]]:
    """处理 pos_push 推送 (v118: 持仓变化直接覆盖本地)"""
    stock_code = _str(row.get('stock_code', ''))
    if not stock_code:
        return None

    last_vol = _int(row.get('last_vol', 0))
    vol = _int(row.get('vol', 0))
    avl_vol = _int(row.get('avl_vol', 0))
    avg_price = _float(row.get('avg_price', 0))

    incoming = {
        'last_vol': last_vol,
        'vol': vol,
        'avl_vol': avl_vol,
        'cost_price': avg_price,
    }

    # 查询现有 Position
    pos_list = Positions.query_by('stock_code', stock_code, limit=1)
    pos = pos_list[0] if pos_list else None

    if pos is None:
        # 新建 Position (broker 已经看到持仓, 本地没有)
        # v118: 不需要 reconcile 兜底, 直接由 pos_push 驱动创建
        new_row = Positions.add_one({
            'stock_code': stock_code,
            'stock_name': '',     # 持仓变化推送不带名称, 名称由 stocks 表 lookup
            'last_vol': last_vol,
            'vol': vol,
            'avl_vol': avl_vol,
            'cost_price': avg_price,
            'synced_at': _utcnow(),
            'synced_from': 'pos_push',   # v118: 标识来源
        })
        return {"position": _position_to_out_dict(new_row)}

    # REQ-PUSH-034: 4 业务字段与 DB 全等 → 跳过落库 + 跳过广播
    if _fields_unchanged(pos, incoming):
        return None

    # 已存在: broker 推送覆盖本地 (broker 永远权威)
    Positions.update_one({
        'last_vol': last_vol,
        'vol': vol,
        'avl_vol': avl_vol,
        'cost_price': avg_price,
        'synced_at': _utcnow(),
        'synced_from': 'pos_push',   # v118
    }, stock_code=stock_code)

    # 重新查一次返回最新行 (确保返回给前端的字段值与 DB 一致)
    pos_list2 = Positions.query_by('stock_code', stock_code, limit=1)
    return {"position": _position_to_out_dict(pos_list2[0])}