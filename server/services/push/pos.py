"""
push/pos.py — v118 pos_push 处理

broker 端 position_callback 推送 pos_push 事件 (xtquant 协议):
  stock_code, last_vol, volume, avl_amt, avg_price

设计 (v118 后):
  - pos_push 是持仓数据的唯一权威源
  - trd_cfm 不再处理持仓 (仅写 trades + orders)
  - reconcile 不再覆盖持仓 (仅初始化时用 qry_positions 同步)

行为 (v128.1 2026-08-12):
  - broker 端已做去重, server 不再做 diff 判断 — 任何 pos_push 进来都直接
    upsert DB 并返回 PositionOut 给 dispatcher 广播 position_update
  - init reconcile 窗口仍由 suppress_pos_push() context manager 抑制
    (覆盖 qry_positions 等待 + 全表覆盖窗口, 避免 init 后 push 洪峰)
"""
from typing import Any, Dict, Optional

from server.tables import Positions
from server.utils.time import _utcnow
from server.services.push.helpers import _int, _float, _round4, _str, _position_to_out_dict

# change init-push-gate: init reconcile 期间抑制 pos_push (DB 写 + 广播)
#   日初 do_reconcile(init) 全表覆盖 positions 期间, broker 并发 pos_push 会把每条
#   判成"新增/变化"而广播洪峰 (前端 gate 丢弃前已造成 2197 条广播)。
#   但 init 后前端 resetForNewDay 会 RPC 全量拉权威数据, 窗口期 pos_push 是冗余 → 整体抑制。
#   incremental reconcile 不抑制 (不动 positions)。
_SUPPRESS_POS_PUSH = False


class suppress_pos_push:
    """context manager: init reconcile 期间抑制 pos_push 处理 (线程安全, 原子赋值).

    init_trading_day 用 `with suppress_pos_push(): result = await do_reconcile(init)` 包住,
    覆盖 qry_positions 等待 + 全表覆盖窗口。退出时无条件复位 (含异常路径)。
    """
    def __enter__(self):
        global _SUPPRESS_POS_PUSH
        _SUPPRESS_POS_PUSH = True

    def __exit__(self, exc_type, exc_val, exc_tb):
        global _SUPPRESS_POS_PUSH
        _SUPPRESS_POS_PUSH = False
        return False


def handle_pos_push(db, row: Dict[str, Any], ts: str) -> Optional[Dict[str, Any]]:
    """处理 pos_push 推送 (v118: 持仓变化直接覆盖本地; v128.1: 无 server 端去重)

    broker 端已做去重, 本函数只负责 upsert DB + 返回广播 payload.
    broker wire 字段 (xtquant 协议):
      stock_code / last_vol / volume / avl_amt / avg_price
    与 parsers_business._parse_positions 的 rename 对齐:
      volume → vol, avl_amt → avl_vol, avg_price → cost_price
    """
    # change init-push-gate: init reconcile 期间抑制 — 不查库 / 不落库 / 不广播
    if _SUPPRESS_POS_PUSH:
        return None

    stock_code = _str(row.get('stock_code', ''))
    if not stock_code:
        return None

    last_vol = _int(row.get('last_vol', 0))
    vol = _int(row.get('volume', 0))            # broker wire: volume
    avl_vol = _int(row.get('avl_amt', 0))       # broker wire: avl_amt
    cost_price = _round4(row.get('avg_price', 0))  # broker wire: avg_price, v130+ 统一 4 位

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
            'cost_price': cost_price,
            'synced_at': _utcnow(),
            'synced_from': 'pos_push',   # v118: 标识来源
        })
        return {"position": _position_to_out_dict(new_row)}

    # 已存在: broker 推送直接覆盖本地 (broker 永远权威, 无 server 端 diff)
    Positions.update_one({
        'last_vol': last_vol,
        'vol': vol,
        'avl_vol': avl_vol,
        'cost_price': cost_price,
        'synced_at': _utcnow(),
        'synced_from': 'pos_push',   # v118
    }, stock_code=stock_code)

    # 重新查一次返回最新行 (确保返回给前端的字段值与 DB 一致)
    pos_list2 = Positions.query_by('stock_code', stock_code, limit=1)
    return {"position": _position_to_out_dict(pos_list2[0])}