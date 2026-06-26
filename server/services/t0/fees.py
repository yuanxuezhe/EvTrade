"""
t0_fees.py — T0 费率与精度工具

提供：
- _q2 / _q4: 金融精度四舍五入
- calc_commission_and_tax: 手续费 + 印花税（卖出方向）
- 共享常量: 失败单状态 / 买卖方向码
"""
from decimal import Decimal, ROUND_HALF_UP
from typing import Tuple

from server.models.orm import FeeConfig


# 失败单状态：废单不计入
_FAILED_STATUS = "55"
# 卖出方向 order_type
_SELL_TYPE = "24"
# 买入方向 order_type
_BUY_TYPE = "23"


def _q2(x):
    """保留 2 位小数（金融用 round-half-up）"""
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _q4(x):
    """保留 4 位小数（胜率/收益率）"""
    return float(Decimal(str(x)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def calc_commission_and_tax(amount, fee_cfg, direction):
    """算手续费 + 印花税（卖出）

    Args:
        amount: 成交金额（价格 × 数量）
        fee_cfg: 费率配置
        direction: 'BUY' / 'SELL'

    Returns:
        (commission, stamp_tax)
    """
    commission = round(amount * fee_cfg.commission_rate, 2)
    # 最低佣金兜底（A 股规则：佣金 < 5 元时按 5 元收）
    min_c = getattr(fee_cfg, "min_commission", 0.0) or 0.0
    if min_c > 0 and commission < min_c and amount > 0:
        commission = min_c
    stamp_tax = 0.0
    if direction == "SELL":
        stamp_tax = round(amount * fee_cfg.stamp_tax_rate, 2)
    return commission, stamp_tax
