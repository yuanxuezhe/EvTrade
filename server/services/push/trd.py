"""
push_handler_trd.py — trd_cfm 处理（(trd_date, order_no) 唯一匹配）

行为：
- (REQ-TRADE-032): trd_cfm 不动 Order 累计；只插 Trade
  (Order traded_volume/traded_amount/avg_price/status 由 ord_cfm 推送一次写入)
- 字段命名统一 (REQ-TRADE-033, 消歧义):
  - row['remark']      → order_no        (即我司系统订单号, 我们下单时送入到 broker.remark)
  - row['order_id']    → order_id         (即柜台/券商委托号, broker xtquant 系统分配)
- 唯一匹配维度 (REQ-TRADE-034):
  - **只用 (trd_date, order_no) 命中本地 Order** — 不用 order_id 兜底

行为：
- 用 broker.remark（= 本地 order_no）匹配本地 Order
- Trade 幂等插入：PK 存在则跳过
- 读 broker 原字段 `traded_id`/`traded_volume`/`traded_price`/`traded_amount`/`traded_time`

持仓数据流 (consolidate-position-data-flow 后):
- 持仓由 pos_push 驱动 (见 push/pos.py), trd_cfm 不写 positions
"""
from typing import Any, Dict, Optional

from server.tables import Orders, Trades, Positions
from server.repo.orders import _get_active_trd_date
from server.services.push.helpers import _float, _int, _str, _round_scale, _order_to_out_dict, _trade_to_out_dict, _position_to_out_dict
from server.utils.time import _utcnow, parse_broker_ts
from server.repo.stocks import get_stock_scale


def handle_trd_cfm(db, row: Dict[str, Any], ts: str) -> Optional[Dict[str, Any]]:
    """处理 trd_cfm 推送（broker 原字段名）"""
    trd_date = _str(row.get('trade_date', '')) or _get_active_trd_date(db)
    if not trd_date or len(trd_date) != 8:
        trd_date = _get_active_trd_date(db)

    order_no = _str(row.get('remark', ''))
    order_id = _str(row.get('order_id', ''))

    if not order_no:
        print(f"[trd_cfm] WARN: no order_no (remark 缺失), 跳过 traded_id={row.get('traded_id', '')}")
        return None

    trade_id = _str(row.get('traded_id', ''))
    if not trade_id:
        trade_id = "{}-{}".format(order_no, row.get('traded_time', ''))

    # 幂等: 已存在则不重复插入 (PK = (trd_date, order_no, trade_id))
    existing = Trades.query_one(trd_date=trd_date, order_no=order_no, trade_id=trade_id)
    if existing:
        return None

    # 唯一匹配 (trd_date, order_no) (REQ-TRADE-034)
    order = Orders.query_one(order_no=order_no, trd_date=trd_date)

    price = _float(row.get('traded_price', 0))
    volume = _int(row.get('traded_volume', 0))
    amount = round(price * volume, 2) if volume else 0.0

    broker_order_type = _str(row.get('order_type', ''))
    final_order_type = broker_order_type or (order.order_type if order else '')

    # Trades.add_one(dict) → 返回 Row
    trade = Trades.add_one({
        'trd_date': trd_date,
        'order_no': order_no,
        'trade_id': trade_id,
        'stock_code': _str(row.get('stock_code', '')),
        'order_type': final_order_type,
        'price': price,
        'volume': volume,
        'amount': amount,
        'trade_time': parse_broker_ts(_str(row.get('traded_time', ts)), trd_date, tz='local'),
        'trade_type': _int(row.get('trade_type', 0), 0),
    })

    # trd_cfm 不累加 Order
    if not order:
        print(f"[trd_cfm] WARN: no order for trade_id={trade_id} (order_no={order_no}, order_id={order_id}) — Trade 行已留存")

    # 持仓数据源是 broker 推 pos_push (xtquant position_callback);
    # trd_cfm 仅写 trades + orders, 不写 positions
    position_dict = None

    print(f"[trd_cfm] inserted trade_id={trade_id} order_no={order_no} vol={trade.volume} px={trade.price}")

    return {
        "trade": _trade_to_out_dict(trade),
        "order": _order_to_out_dict(order),
        "position": position_dict,  # trd_cfm 不带 position (pos_push 单独推送)
    }


def _update_position_vol(
    db,
    stock_code: str,
    order_type: str,
    volume: int,
    *,
    order_no: str = "",
    trade_id: str = "",
    trade_price: float = 0.0,
) -> Optional[dict]:
    """增量更新 Position（按 T0/非 T0 规则）

    返回更新后 Position 行的 out_dict (供 dispatcher 广播 position_update 用)
         - Position 不存在 + 买入自动创建 → 同样返回 out_dict
         - Position 不存在 + 卖出跳过 → 返回 None

    设计要点:
    - vol 永远按 order_type 累加: 买 += qty, 卖 -= qty
    - avl_vol 规则 (T0 决定):
        * T0 股票 买: avl_vol += qty (T+0 当日可卖)
        * T0 股票 卖: avl_vol -= qty
        * 非 T0 股票 买: avl_vol 不变 (T+1 解禁, 当日不可卖)
        * 非 T0 股票 卖: avl_vol -= qty (可卖存量)
    - Position 不存在 + 买入: 自动创建 Position 行
    - Position 不存在 + 卖出: WARN 跳过 (不允许凭空卖, 等 day-init reconcile)
    """
    if not stock_code or not volume:
        return

    from server.repo.stocks import get_is_t0_able

    is_t0 = get_is_t0_able(db, stock_code)
    # Positions 表主键是 stock_code (单字段)
    pos_list = Positions.query_by('stock_code', stock_code, limit=1)
    pos = pos_list[0] if pos_list else None

    # Position 不存在 → 买入自动创建
    if pos is None:
        if order_type == "23":  # 买
            new_row = Positions.add_one({
                'stock_code': stock_code,
                'stock_name': "",
                'last_vol': 0,
                'vol': volume,
                'avl_vol': volume if is_t0 else 0,
                'cost_price': _round_scale(trade_price, get_stock_scale(db, stock_code)),  # 建仓成本按 scale 保留精度
                'synced_at': _utcnow(),
                'synced_from': "push_partial",
            })
            print(
                "[TRD→POSITION] auto-created Position stock_code={} vol={} avl_vol={} t0={} "
                "(order_no={}, trade_id={})".format(
                    stock_code, volume, volume if is_t0 else 0, is_t0,
                    order_no, trade_id,
                )
            )
            # 返回新建行的 out_dict, 让 dispatcher 推 position_update
            return _position_to_out_dict(new_row)
        else:  # 卖
            print(
                "[TRD→POSITION] WARN: sell but no Position for stock_code={}, "
                "skipping (order_no={}, trade_id={}, vol={})".format(
                    stock_code, order_no, trade_id, volume,
                )
            )
            return None

    # Position 存在 → 按规则增量
    if order_type == "23":  # 买
        pos.vol = (pos.vol or 0) + volume
        if is_t0:
            pos.avl_vol = (pos.avl_vol or 0) + volume
    elif order_type == "24":  # 卖
        pos.vol = (pos.vol or 0) - volume
        pos.avl_vol = (pos.avl_vol or 0) - volume
    else:
        print(
            "[TRD→POSITION] WARN: unknown order_type={} for stock_code={}, "
            "skipping (order_no={}, trade_id={})".format(
                order_type, stock_code, order_no, trade_id,
            )
        )
        return

    pos.synced_at = _utcnow()
    if not pos.synced_from:
        pos.synced_from = "push_partial"

    # pos.update() 把累加字段一次性 UPDATE
    pos.update(Positions, stock_code=stock_code)

    avl_delta = volume if (order_type == "23" and is_t0) else (-volume if order_type == "24" else 0)
    print(
        "[TRD→POSITION] updated Position stock_code={} order_type={} vol_delta={} avl_delta={} "
        "new_vol={} new_avl={} t0={} (order_no={}, trade_id={})".format(
            stock_code, order_type,
            volume if order_type == "23" else -volume,
            avl_delta,
            pos.vol, pos.avl_vol, is_t0,
            order_no, trade_id,
        )
    )

    # 返回 update 后 Position 行的 out_dict, dispatcher 会推 position_update
    #   关键: 必须在 pos.update() 之后返回 (字段已刷新), 否则前端 vol/avl_vol 会差一帧
    return _position_to_out_dict(pos)