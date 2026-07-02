"""
order_status.py — 委托 status 共享模块（v11: broker xtconstant 字典对齐）

提供：
- ORDER_STATUS: broker xtconstant 字典 (11 条: 48-57 + 255), 状态码 → 中文
- TERMINAL_STATUSES: 终态集合（52/53/54/55/56/57, 含 broker 52=部成待撤）
- is_cancellable(code): 触发码 (48/49/50, 含 broker 50=已报也可撤)
- _status_msg(status): 状态码 → 中文 (fallback when broker 不推 status_msg)
- _infer_order_status(order, broker_status=None): v8 改 cancelled_volume 主轴 + v11 改 broker 码输出
- _get_active_trd_date(db): 短连接查当前激活交易日, 未激活用 MAX(trd_date) 兜底

被 4 个 handler（ord/trd/pos/ast）共用, 被 test_push_handlers.py 直接测。

v11 修订 (align-status-codes-to-xtconstant):
- 删 `class Status` (含 _LABEL 死代码 + 9 个英文常量)
- `ORDER_STATUS` 改为 broker xtconstant 字典 (10 条 + 255)
- `TERMINAL_STATUSES` 含 broker 52 (部成待撤)
- `is_cancellable` 含 broker 50 (已报也可撤)
- `_infer_order_status` 输出码全集 {50, 53, 54, 55, 56} (broker 码)
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from server.models.orm import Order, SysStatus


# ================================================================
# broker xtconstant 字典（v11, 1:1 对齐）
# 权威源: iquant/xtquant_api.py 第 130-200 行 / 280-340 行
# ================================================================
ORDER_STATUS = {
    "48":  "未报",          # ORDER_UNREPORTED
    "49":  "待报",          # ORDER_WAIT_REPORTING
    "50":  "已报",          # ORDER_REPORTED
    "51":  "已报待撤",      # ORDER_REPORTED_CANCEL
    "52":  "部成待撤",      # ORDER_PARTSUCC_CANCEL
    "53":  "部成部撤",      # ORDER_PART_CANCEL
    "54":  "已撤",          # ORDER_CANCELED
    "55":  "部成",          # ORDER_PART_SUCC
    "56":  "已成",          # ORDER_SUCCEEDED
    "57":  "废单",          # ORDER_JUNK
    "255": "未知",          # ORDER_UNKNOWN
}

# 终态集合（v11: 含 broker 52=部成待撤, 删 broker 55=部成 PART_SUCC 非终态 - 与 broker 终态口径一致）
# 含 broker 52 (部成待撤, 撤单过渡) + broker 53/54/56/57 (部成部撤/已撤/已成/废单)
# 不含 broker 55 (PART_SUCC 部成, 可继续累计到 broker 56 已成)
TERMINAL_STATUSES = ('52', '53', '54', '56', '57')


def is_cancellable(code: str) -> bool:
    """是否可撤单（v11: 含 broker 50=已报 也可撤）

    触发码 (48, 49, 50) 对应 broker UNREPORTED / WAIT_REPORTING / REPORTED.
    broker 51=已报待撤 已算"撤单中", 不再可发起新撤单.
    """
    return code in ('48', '49', '50')


def _status_msg(status: str) -> str:
    """状态码 → 中文 (broker xtconstant 字典)"""
    return ORDER_STATUS.get(status, '')


def _infer_order_status(order: Order, broker_status: Optional[str] = None) -> str:
    """委托 status 本地推断（v8 改: cancelled_volume 主轴 + v11 改: broker 码输出）

    Args:
        order: Order 实例, 需要 traded_volume / cancelled_volume / volume / status (当前值) 字段
        broker_status: 可选, broker ord_cfm 推的 status 字段 (52/53/54 视为撤单类, broker xtconstant 码)
                     trd_cfm 调用时传 None (trd_cfm 永远不写撤单类状态)

    Returns:
        推断后的 status: 50 / 53 / 54 / 55 / 56 (broker xtconstant 码全集)

    规则 (v8 cancelled_volume 主轴 + v11 broker 码输出):
      1. 当前 status 已是终态 (52/53/54/56/57, 不含 broker 55=部成 PART_SUCC 非终态) → 保持, 不再推断
         (避免 trd_cfm 累计覆盖 ord_cfm 写的撤单终态; broker 55=部成 仍可继续累计到 broker 56 已成)
      2. 撤单主轴 (cum_cancelled):
         - cum_cancelled >= vol                 → 54 (broker 已撤)
         - cum_cancelled > 0 && cum_traded > 0  → 53 (broker 部成部撤)
         - cum_cancelled > 0                    → 54 (部分撤单无成交, 也视作已撤)
      3. broker_status 给出且在 (52, 53, 54) → 撤单类信号 (兼容老 broker 协议)
         - cum_traded = 0                       → 54 (broker 已撤)
         - 0 < cum_traded < vol                 → 53 (broker 部成部撤)
         - cum_traded = vol                     → 56 (broker 已成)
      4. 累计推断 (cum_traded)
         - cum_traded = 0                       → 50 (broker 已报)
         - 0 < cum_traded < vol                 → 55 (broker 部成)
         - cum_traded = vol                     → 56 (broker 已成)
    """
    current = order.status or '48'

    # 1. 终态保持
    if current in TERMINAL_STATUSES:
        return current

    cum = order.traded_volume or 0
    cum_cancelled = order.cancelled_volume or 0
    vol = order.volume or 0

    # 2. 撤单主轴 (v8 新增, 优先于 broker_status 判定)
    if cum_cancelled >= vol and vol > 0:
        return '54'  # broker 已撤: 撤单数 ≥ 委托数
    if cum_cancelled > 0 and cum > 0:
        return '53'  # broker 部成部撤: 既有成交又有撤单
    if cum_cancelled > 0 and cum == 0:
        return '54'  # 部分撤单 (无成交) → 视作 broker 已撤 (运营角度)

    # 3. broker 推了撤单类 status (兼容老 broker 协议, 无 cancelled_volume 字段时)
    # v11: 触发码含 broker 51=已报待撤 (broker 撤单类全集: 51/52/53/54)
    if broker_status and broker_status in ('51', '52', '53', '54'):
        if cum == 0:
            return '54'
        if cum < vol:
            return '53'
        return '56'  # broker 已成, broker 撤单无意义

    # 4. 累计推断 (v11 broker 码)
    if cum == 0:
        return '50'  # broker 已报
    if cum < vol:
        return '55'  # broker 部成
    return '56'  # broker 已成


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