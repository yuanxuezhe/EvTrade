"""
order_status.py — 委托 status 共享模块（v8: cancelled_volume 主轴）

提供：
- Status 类: 状态码枚举 + label/is_terminal/is_cancellable
- ORDER_STATUS: 状态码 → 本地文字 映射（兼容老代码）
- TERMINAL_STATUSES: 终态集合（51/52/53/54/55/56）
- _status_msg(status): 状态码 → 文字
- _infer_order_status(order, broker_status=None): v8 改：cancelled_volume 主轴的本地推断
- _get_active_trd_date(db): 短连接查当前激活交易日，未激活用 MAX(trd_date) 兜底

被 4 个 handler（ord/trd/pos/ast）共用，被 test_push_handlers.py 直接测。
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from server.models.orm import Order, SysStatus


# ================================================================
# 订单状态枚举（原 constants.OrderStatus 合并至此）
# ================================================================
class Status:
    """订单状态枚举（与原 constants.OrderStatus 等价）"""
    PENDING_REPORT = "48"    # 待报
    REPORTED = "49"          # 已报
    PARTIAL = "50"           # 部分成交
    PARTIAL_CANCEL = "51"    # 已成
    FILLED = "52"            # 已撤
    REJECTED = "53"          # 已拒
    CANCELLED = "54"         # 撤单中
    PARTIAL_CANCEL2 = "55"   # 部分撤单/废单
    PARTIAL_FILL_CANCEL = "56"  # 部成部撤

    _LABEL = {
        "48": "待报",
        "49": "已报",
        "50": "部分成交",
        "51": "已撤",
        "52": "已成交",
        "53": "已拒",
        "54": "撤单中",
        "55": "失败",
        "56": "部成部撤",
        "99": "未知",
    }

    @classmethod
    def label(cls, code: str) -> str:
        return cls._LABEL.get(code, code)

    @classmethod
    def is_terminal(cls, code: str) -> bool:
        """是否终态（不可再变）"""
        return code in TERMINAL_STATUSES

    @classmethod
    def is_cancellable(cls, code: str) -> bool:
        """是否可撤单"""
        return code in ("48", "49")


# 兼容老代码的映射/集合
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

TERMINAL_STATUSES = ('51', '52', '53', '54', '55', '56')


def _status_msg(status: str) -> str:
    """状态码 → 本地文字"""
    return ORDER_STATUS.get(status, '')


def _infer_order_status(order: Order, broker_status: Optional[str] = None) -> str:
    """委托 status 本地推断（v8 改：cancelled_volume 主轴）

    Args:
        order: Order 实例,需要 traded_volume / cancelled_volume / volume / status(当前值) 字段
        broker_status: 可选,broker ord_cfm 推的 status 字段(52/53/54 视为撤单类)
                     trd_cfm 调用时传 None(trd_cfm 永远不写撤单类状态)

    Returns:
        推断后的 status: 49 / 50 / 51 / 53 / 56

    规则 (v8: cancelled_volume 主轴):
      1. 当前 status 已是终态(51/52/53/54/55/56) → 保持,不再推断
         (避免 trd_cfm 累计覆盖 ord_cfm 写的撤单终态)
      2. 撤单主轴(cum_cancelled):
         - cum_cancelled >= vol                 → 53 (已撤)
         - cum_cancelled > 0 && cum_traded > 0  → 56 (部成部撤)
         - cum_cancelled > 0                    → 53 (部分撤单无成交,也视作已撤)
      3. broker_status 给出且在 (52, 53, 54) → 撤单类信号(兼容老 broker 协议)
         - cum_traded = 0                       → 53 (已撤)
         - 0 < cum_traded < vol                 → 56 (部成部撤)
         - cum_traded = vol                     → 51 (已成)
      4. 累计推断 (cum_traded)
         - cum_traded = 0                       → 49 (已报)
         - 0 < cum_traded < vol                 → 50 (部成)
         - cum_traded = vol                     → 51 (已成)
    """
    current = order.status or '48'

    # 1. 终态保持
    if current in TERMINAL_STATUSES:
        return current

    cum = order.traded_volume or 0
    cum_cancelled = order.cancelled_volume or 0
    vol = order.volume or 0

    # 2. 撤单主轴(v8 新增,优先于 broker_status 判定)
    if cum_cancelled >= vol and vol > 0:
        return '53'  # 已撤:撤单数 ≥ 委托数
    if cum_cancelled > 0 and cum > 0:
        return '56'  # 部成部撤:既有成交又有撤单
    if cum_cancelled > 0 and cum == 0:
        return '53'  # 部分撤单(无成交) → 视作已撤(运营角度)

    # 3. broker 推了撤单类 status(兼容老 broker 协议,无 cancelled_volume 字段时)
    if broker_status and broker_status in ('52', '53', '54'):
        if cum == 0:
            return '53'
        if cum < vol:
            return '56'
        return '51'  # 已成,broker 撤单无意义

    # 4. 累计推断
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
