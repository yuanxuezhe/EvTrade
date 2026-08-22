"""
push_handler_ord.py — ord_cfm 处理（(trd_date, order_no) 唯一匹配）

行为：
- 字段命名统一 (REQ-TRADE-033):
  - row['remark']      → order_no        (即我司系统订单号, 我们下单时送入到 broker.remark)
  - row['order_id']    → order_id         (即柜台/券商委托号, broker xtquant 系统分配)
- 唯一匹配维度 (REQ-TRADE-034):
  - **只用 (trd_date, order_no) 命中本地 Order** — 不用 order_id 匹配 (易错位)
  - (trd_date 是 row 里提供的我们系统当前交易日; 落库 Order 时也会按 trd_date 索引)
- 委托确认规则 (用户给定):
  - 状态不是已撤/废单 (52/54/57 + 51 已报待撤 53 部成部撤) → set row.status = 已报 (50)
  - 状态是撤单类 (52/53/54/57) → 用 broker_status 直接写 (与 broker 字典对齐)
- 读 broker 原字段 `order_status`（不 alias `status`）、`order_time`、`order_volume`
"""
from typing import Any, Dict, Optional

from server.tables import Orders
from server.repo.orders import _get_active_trd_date
from server.services.push.helpers import _float, _int, _str, _order_to_out_dict
from server.utils.time import _utcnow, parse_broker_ts
from server.repo.stocks import get_stock_scale  # 价格按 stock.scale round


def handle_ord_cfm(db, row: Dict[str, Any], ts: str) -> Optional[Dict[str, Any]]:
    """处理 ord_cfm 推送（只填 order_id + 推断 status + order_time）

    字段命名 (REQ-TRADE-033):
      order_id         柜台委托号 (柜台系统分配, 写入 Order.order_id)
      order_no         系统订单号 (我司下单时送入到 broker.remark, broker 回填到 row.remark, 对应 Order.order_no)
      stock_code
      order_type
      price_type
      price
      order_volume     broker 改单后真实 volume
      order_status     broker 原字段
      order_time       标准格式
      traded_volume    broker 累计成交量
      traded_price     broker 最近成交价 (作为均价)
      strategy_name    透传

    匹配 (REQ-TRADE-034):
      唯一匹配维度: (trd_date, order_no) → Order.order_no (Order.order_no + trd_date 唯一索引)
      不用 order_id 匹配 (因 broker 系统重启或跨日容易错位)
    """
    # 字段名直接用 row['remark'] 接 order_no, row['order_id'] 接柜台 order_id
    order_no = _str(row.get('remark', ''))  # ← 柜台 broker.remark = 我们下传的 order_no
    order_id = _str(row.get('order_id', ''))  # ← 柜台 xtquant 系统分配的 broker order id
    trd_date = _str(row.get('trd_date', '')) or _get_active_trd_date(db)
    broker_status = _str(row.get('order_status', ''))  # broker 原字段名

    if not order_no:
        print("[ord_cfm] skip: no order_no (row.remark empty)")
        return None

    # 唯一匹配 (trd_date, order_no) (REQ-TRADE-034) — 不用 order_id 兜底
    order = Orders.query_one(trd_date=trd_date, order_no=order_no)

    if not order:
        # 极端情况:push 来了但本地没有 (重启后丢单 / 跨日错位)
        # 不创建新单(避免错位),只打日志
        print(f"[ord_cfm] WARN: no local Order for trd_date={trd_date} order_no={order_no} (broker order_id={order_id})")
        return None

    # broker order_id 直接写入(覆盖 NULL)
    if order_id and order.order_id != order_id:
        order.order_id = order_id

    # 累加 cancelled_volume(broker 不同版本字段名兼容)
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
    else:
        # R2b broker 未推 cancelled_volume + broker_status 落在 broker 撤单类 → 本地兜底抹平到 volume
        # 仅 52/53/54 触发 flatten (broker 撤单类全集, 不含 51/55)
        if broker_status in ('52', '53', '54') and (order.cancelled_volume or 0) < (order.volume or 0):
            order.cancelled_volume = order.volume

    # 覆盖 order_volume（broker 改单后真实委托数）
    broker_volume = _int(row.get('order_volume', None), 0)
    if broker_volume > 0 and broker_volume != order.volume:
        order.volume = broker_volume

    # 委托确认规则 (保留做兜底)
    CANCEL_LIKE_STATUSES = ('52', '53', '54', '57')

    # 直接用 broker_status 落库（已部成/已成/部撤/已撤/废单 都保留）
    # 仅当 broker_status 缺失时兜底为 '50'（已报）以兼容异常 broker
    order.status = broker_status or order.status or '50'
    # 直接用 broker 推的 status_msg
    order.status_msg = _str(row.get('status_msg', ''))

    # 写入 order_time（parse_broker_ts 统一为标准格式 "YYYY-MM-DD HH:MM:SS.fff"）
    broker_order_time = _str(row.get('order_time', ''))
    if broker_order_time:
        order.order_time = parse_broker_ts(broker_order_time, order.trd_date, tz='local')

    # 累加 cumulative 成交量 + 成交均价（broker ord_cfm 推送的字段, 不依赖 trd_cfm 累加）
    # broker 字段: traded_volume (累计成交量) / traded_price (最近成交价, 用作均价近似)
    # 注: xtquant_api.py:260-271 broker 仅推 traded_volume + traded_price, 没有 avg_price/cum_volume
    cum_volume = _int(row.get('traded_volume', 0))
    cum_avg_price = _float(row.get('traded_price', 0))  # broker 推的最近成交价作为均价
    if cum_volume > 0:
        # 不超过委托量
        if order.volume and cum_volume > order.volume:
            cum_volume = order.volume
        order.traded_volume = cum_volume
    if cum_avg_price > 0:
        # 按 stock.scale round 均价 + 成交金额 (scale>6 兜底 2)
        scale = get_stock_scale(db, order.stock_code)
        if scale > 6:
            scale = 2
        order.traded_amount = round(cum_avg_price * order.traded_volume, scale)
        order.avg_price = round(cum_avg_price, scale)

    order.pushed_at = _utcnow()
    order.updated_at = _utcnow()

    # Row.update() 把所有累加字段一次性 UPDATE
    order.update(Orders, trd_date=trd_date, order_no=order_no)

    print(f"[ord_cfm] updated trd_date={trd_date} order_no={order_no} order_id={order_id} status={order.status} (broker_status={broker_status}, cum={order.traded_volume}/{order.volume}, avg={order.avg_price})")

    # 委托推送始终广播, 让前端委托表实时刷新成交数量/成交均价/成交金额/状态
    #   (若只推部分状态, 部成/已成/已撤/部撤状态前端不刷新,
    #   只能等 bootstrap refreshAll 兜底 — 纯撤单无成交时永远不刷新)
    return _order_to_out_dict(order)
