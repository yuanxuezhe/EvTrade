"""
push_handler_ord.py — ord_cfm 处理（v10: broker 原字段名 + order_time 写库 + v59 委托确认规则）

行为：
- 用 broker.remark（= 本地 order_no）匹配本地 Order
- 写入 broker_order_id
- 累加 cancelled_volume（兼容 cancelled_volume / cancel_volume / withdrawn_volume 字段名）
- v59 委托确认规则 (用户给定):
  - 状态不是已撤/废单 (52/54/57 + 51 已报待撤 53 部成部撤) → set row.status = 已报 (50)
  - 状态是撤单类 (52/53/54/57) → 用 broker_status 直接写 (与 broker 字典对齐)
  - 不再让 _infer_order_status 把 broker_status 当信号重推断 (防 broker_status='55' 误把已部成当已撤)
- 成交累计 (trd_cfm) 仍走 _infer_order_status 推断 (基于 cumulative)
- v10 字段对齐：读 broker 原字段 `order_status`（不再 alias `status`）、`order_time`、`order_volume`
"""
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from server.models.orm import Order
from server.repo.orders import _infer_order_status, _status_msg
from server.services.push.helpers import _int, _str, _order_to_out_dict
from server.utils.time import _utcnow, parse_broker_ts  # bugfix: were wrongly imported from helpers (never existed there)


def handle_ord_cfm(db: Session, row: Dict[str, Any], ts: str) -> Optional[Dict[str, Any]]:
    """处理 ord_cfm 推送（v10: 简化为只填 order_id + 推断 status + order_time）

    柜台字段（v10 broker 原字段名，权威源: iquant/xtquant_api.py 第 282-295 行）:
      order_id         柜台委托号
      remark           委托备注（即我们下传的本地的 order_no）
      stock_code
      order_type
      price_type
      price
      order_volume     v10 新增：broker 改单后真实 volume
      order_status     v10 broker 原字段（48/49/50/51/52/53/55），喂给 _infer_order_status
      order_time       v10 新增：标准格式 (commit 3 解析)
      strategy_name    v10 新增：透传
    """
    broker_order_id = _str(row.get('order_id', ''))
    broker_remark = _str(row.get('remark', ''))  # ← broker 透传回来的 order_no
    broker_status = _str(row.get('order_status', ''))  # v10: 原字段名

    if not broker_order_id and not broker_remark:
        print("[ord_cfm] skip: no order_id and no remark")
        return None

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
        return None

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
    else:
        # change system-delegation-price-fill-calc: R2b broker 未推 cancelled_volume + broker_status 落在 broker 撤单类 → 本地兜底抹平到 volume
        # v59 bug fix: 仅 52/53/54 触发 flatten (broker 撤单类全集, 不含 51/55)
        #   - 51 (已报待撤) 是过程态, 不一定真撤, flatten 会过早标记已撤
        #   - 55 (部成) 是成交过程态, 永远不该 flatten (55 → cancelled=vol → infer → 54 已撤, 错)
        #   - 57 (废单) 单独处理: 直接写 status=57, 不 flatten
        if broker_status in ('52', '53', '54') and (order.cancelled_volume or 0) < (order.volume or 0):
            order.cancelled_volume = order.volume

    # v10: 覆盖 order_volume（broker 改单后真实委托数）
    broker_volume = _int(row.get('order_volume', None), 0)
    if broker_volume > 0 and broker_volume != order.volume:
        order.volume = broker_volume

    # v78 (REQ-TRADE-029): 已报后续不处理
    #   - 当前 status 已在 ALREADY_REPORTED_STATUSES (50/51/55) → broker 再推同委托确认
    #     (增量 order_id/cancelled_volume 等) → return None, dispatcher 跳过 ws 广播
    #     避免前端重复刷新
    #   - 当 broker_status 落入 CANCEL_LIKE_STATUSES (52/53/54/57 撤单类) → 必须继续,
    #     让撤单终态覆盖 (v59 已对, 不变)
    # v59 旧规则保留做兜底:
    #   CANCEL_LIKE_STATUSES = (52/53/54/57)  → order.status = broker_status
    #   其他 broker_status                  → order.status = '50' (已报)
    CANCEL_LIKE_STATUSES = ('52', '53', '54', '57')
    ALREADY_REPORTED_STATUSES = ('50', '51', '55')  # 已报 / 已报待撤 / 部成 → 不再处理同委托 ord_cfm

    if order.status in ALREADY_REPORTED_STATUSES and broker_status not in CANCEL_LIKE_STATUSES:
        # v78: 已经"出过"状态事件, 增量信息 (cancelled_volume/order_id) DB 已落但不再 ws 广播.
        # broker 撤单信号必须穿透 (让 cancel-row/部撤/废单 立即生效).
        return None

    if broker_status in CANCEL_LIKE_STATUSES:
        order.status = broker_status
    else:
        order.status = '50'  # 已报
    order.status_msg = _str(row.get('status_msg', '')) or _status_msg(order.status)

    # v10: 写入 order_time（v10 起, parse_broker_ts 统一为标准格式 "YYYY-MM-DD HH:MM:SS.fff"）
    broker_order_time = _str(row.get('order_time', ''))
    if broker_order_time:
        order.order_time = parse_broker_ts(broker_order_time, order.trd_date, tz='local')

    order.pushed_at = _utcnow()
    order.updated_at = _utcnow()

    print("[ord_cfm] updated order_no={} order_id={} status={} (broker_status={}, cum={}/{})".format(
        order.order_no, order.order_id, order.status, broker_status,
        order.traded_volume, order.volume))

    return _order_to_out_dict(order)
