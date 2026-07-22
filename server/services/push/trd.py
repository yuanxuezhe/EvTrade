"""
push_handler_trd.py — trd_cfm 处理（v10 + v78.3 重写 + v79.3 重命名 + (trd_date, order_no) 唯一匹配）

行为：
- v78.3 (REQ-TRADE-032): trd_cfm 不再动 Order 累计；只插 Trade + 改 Position
  (Order traded_volume/traded_amount/avg_price/status 由 ord_cfm 推送一次写入)
- v79.3 (REQ-TRADE-033) 字段命名统一 (消歧义):
  - row['remark']      → order_no        (即我司系统订单号, 我们下单时送入到 broker.remark)
  - row['order_id']    → order_id         (即柜台/券商委托号, broker xtquant 系统分配)
- v79.3 (REQ-TRADE-034) 唯一匹配维度:
  - **只用 (trd_date, order_no) 命中本地 Order** — 不用 order_id 兜底

行为：
- 用 broker.remark（= 本地 order_no）匹配本地 Order
- Trade 幂等插入：PK 存在则跳过
- 同步更新 Order traded_volume / traded_amount / avg_price
- 用 _infer_order_status 本地推断 status（不传 broker_status，trd_cfm 永远不写撤单类）
- v10 字段对齐：读 broker 原字段 `traded_id`/`traded_volume`/`traded_price`/`traded_amount`/`traded_time`

change consolidate-position-data-flow:
- 同时增量更新 Position.vol（intra-day 不依赖 day-init reconcile）
  - order_type "23" (买) → vol += volume
  - order_type "24" (卖) → vol -= volume
- trade_type=1 (cancel-trade) → MUST 跳过 Position.vol 更新（OQ-1 option B；
  DELETE 端点 R1 抹平已负责 vol 调整）
- Position 不存在 → log WARNING + 跳过（admin 必须先 day-init reconcile）
- 不动 Position.cost_price / avl_vol / last_vol (today_buy/today_sell 已删除)
"""
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from server.models.orm import Order, Trade
from server.repo.orders import _get_active_trd_date  # v78.3: trd_cfm 不再调用 _infer_order_status/_status_msg (按字段处理委托表)
from server.services.push.helpers import _float, _int, _str, _order_to_out_dict, _trade_to_out_dict
from server.utils.time import _utcnow, parse_broker_ts
from server.repo.stocks import get_stock_scale  # v80: 价格按 stock.scale round


def handle_trd_cfm(db: Session, row: Dict[str, Any], ts: str) -> Optional[Dict[str, Any]]:
    """处理 trd_cfm 推送（v10: broker 原字段名）

    柜台字段（v10 broker 原字段名，权威源: iquant/xtquant_api.py 第 297-307 行）:
      traded_id        成交编号(UNIQUE,去重用)         v10 原字段名
      order_id         关联委托号(v7 仅作 Order 兜底查找用)
      remark           委托备注(= 本地 order_no,v7 写入 Trade.order_no 入 PK)
      stock_code
      order_type       23=买 24=卖
      traded_price     成交价                              v10 原字段名
      traded_volume    成交量                              v10 原字段名
      traded_amount    成交额                              v10 原字段名
      traded_time      成交时间                            v10 原字段名
      account_id       账号                                v10 透传
      strategy_name    策略名                              v10 透传
    """
    trd_date = _str(row.get('trade_date', '')) or _get_active_trd_date(db)
    if not trd_date or len(trd_date) != 8:
        trd_date = _get_active_trd_date(db)

    # v79.3: 字段名直接用 row['remark'] 接 order_no, row['order_id'] 接柜台 order_id
    order_no = _str(row.get('remark', ''))  # ← 柜台 broker.remark = 我们下传的 order_no
    order_id = _str(row.get('order_id', ''))  # ← 柜台 xtquant 系统分配的 broker order id

    # v79.3 (REQ-TRADE-034): order_no 是 Trade PK 第二段, 缺则不写孤儿 Trade
    if not order_no:
        print(f"[trd_cfm] WARN: no order_no (remark 缺失), 跳过 traded_id={row.get('traded_id', '')}")
        return None

    trade_id = _str(row.get('traded_id', ''))  # v10: 原字段名
    if not trade_id:
        # v7: 用 order_no + traded_time 作 fallback key
        trade_id = "{}-{}".format(order_no, row.get('traded_time', ''))

    # 幂等: 已存在则不重复插入 (PK = (trd_date, order_no, trade_id))
    existing = db.query(Trade).filter_by(
        trd_date=trd_date, order_no=order_no, trade_id=trade_id
    ).first()
    if existing:
        return None

    # v79.3 (REQ-TRADE-034): 唯一匹配 (trd_date, order_no) — 不用 order_id 兜底
    order = db.query(Order).filter_by(
        order_no=order_no, trd_date=trd_date
    ).first()

    # v13: amount 本地算 = price × volume (忽略 broker.traded_amount, 与前端
    #   normalizeTrade 公式一致 — system-delegation-price-fill-calc 设计点)
    #   broker 偶尔推 999.99 / 999.0 等与本地不一致的金额会污染累计 + avg_price
    price = _float(row.get('traded_price', 0))         # v10: 原字段名
    volume = _int(row.get('traded_volume', 0))         # v10: 原字段名
    amount = round(price * volume, 2) if volume else 0.0
    # change fix-trades-direction-server-side: broker trd_cfm 漏推 order_type (xtquant_api.py:275),
    #   之前透传空串到 Trade.order_type='' 导致前端判定 '卖' 反了.
    #   修复: 用本函数上文 (line 72) 已查到的 Order.order_type 反查填充, broker 传了则优先用 broker.
    broker_order_type = _str(row.get('order_type', ''))
    final_order_type = broker_order_type or (order.order_type if order else '')
    trade = Trade(
        trd_date=trd_date,
        order_no=order_no,
        trade_id=trade_id,
        stock_code=_str(row.get('stock_code', '')),
        order_type=final_order_type,
        price=price,
        volume=volume,
        amount=amount,
        # v10: parse_broker_ts 标准化为 "YYYY-MM-DD HH:MM:SS.fff"
        trade_time=parse_broker_ts(_str(row.get('traded_time', ts)), trd_date, tz='local'),
        # change consolidate-position-data-flow: cancel-trade 区分
        # 0=normal 1=cancel-fill (DELETE 端点撤单代理成交)
        trade_type=_int(row.get('trade_type', 0), 0),
    )
    db.add(trade)
    db.flush()

    # v78.3: trd_cfm 不再累加 Order (traded_volume/traded_amount/avg_price/status)
    #   这些字段由 ord_cfm 推送 cum_volume/avg_price 一次写入 (按字段处理委托表)
    #   trd_cfm 只做两件事: (1) 插 Trade (2) 更新 Position 持仓
    if not order:
        print(f"[trd_cfm] WARN: no order for trade_id={trade_id} (order_no={order_no}, order_id={order_id}) — Trade 行已留存")

    # v78.3: trd_cfm 增量更新 Position.vol + avl_vol（按 T0/非 T0 规则）
    #   - trade_type != 0 (cancel-trade) 跳过 (撤单由 DELETE 端点单独处理)
    #   - Position 不存在 + 买入 → 自动创建（vol/avl_vol 初始化）
    #   - Position 不存在 + 卖出 → WARN 跳过（不允许凭空卖）
    if trade.trade_type == 0:
        _update_position_vol(db, trade.stock_code, trade.order_type, trade.volume,
                             order_no=order_no, trade_id=trade_id,
                             trade_price=trade.price)

    print(f"[trd_cfm] inserted trade_id={trade_id} order_no={order_no} vol={trade.volume} px={trade.price}")

    return {
        "trade": _trade_to_out_dict(trade),
        "order": _order_to_out_dict(order),
    }


def _update_position_vol(
    db: Session,
    stock_code: str,
    order_type: str,
    volume: int,
    *,
    order_no: str = "",
    trade_id: str = "",
    trade_price: float = 0.0,
) -> None:
    """v78.3: trd_cfm 增量更新 Position（按 T0/非 T0 规则）

    设计要点:
    - vol 永远按 order_type 累加: 买 += qty, 卖 -= qty
    - avl_vol 规则 (T0 决定):
        * T0 股票 买: avl_vol += qty (T+0 当日可卖)
        * T0 股票 卖: avl_vol -= qty
        * 非 T0 股票 买: avl_vol 不变 (T+1 解禁, 当日不可卖)
        * 非 T0 股票 卖: avl_vol -= qty (可卖存量)
    - Position 不存在 + 买入: 自动创建 Position 行
      (vol = qty, avl_vol = T0 ? qty : 0, cost_price = trade_price)
    - Position 不存在 + 卖出: WARN 跳过 (不允许凭空卖, 等 day-init reconcile)
    - trade_type != 0 由 caller 保证已 skip (撤单由 DELETE 端点单独处理)
    - 异常仅 log 不向上抛 — 不能让 push 链路中断
    """
    if not stock_code or not volume:
        return

    from server.models.orm import Position
    from server.repo.stocks import get_is_t0_able  # v78.3: 内存 cache

    is_t0 = get_is_t0_able(db, stock_code)
    pos = db.query(Position).filter_by(stock_code=stock_code).first()

    # v78.3: 买入时 Position 不存在 → 自动创建
    if pos is None:
        if order_type == "23":  # 买
            pos = Position(
                stock_code=stock_code,
                stock_name="",  # 由 day-init reconcile 后补全
                last_vol=0,
                vol=volume,
                avl_vol=volume if is_t0 else 0,  # T0 当日可卖, 非 T0 次日解禁
                cost_price=trade_price,
                synced_at=_utcnow(),
                synced_from="push_partial",
            )
            db.add(pos)
            print(
                "[TRD→POSITION] auto-created Position stock_code={} vol={} avl_vol={} t0={} "
                "(order_no={}, trade_id={})".format(
                    stock_code, volume, volume if is_t0 else 0, is_t0,
                    order_no, trade_id,
                )
            )
            return
        else:  # 卖
            print(
                "[TRD→POSITION] WARN: sell but no Position for stock_code={}, "
                "skipping (order_no={}, trade_id={}, vol={})".format(
                    stock_code, order_no, trade_id, volume,
                )
            )
            return

    # Position 存在 → 按规则增量
    if order_type == "23":  # 买
        pos.vol = (pos.vol or 0) + volume
        if is_t0:
            pos.avl_vol = (pos.avl_vol or 0) + volume
        # 非 T0 买: avl_vol 不变 (T+1 解禁, 等 reconcile)
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
