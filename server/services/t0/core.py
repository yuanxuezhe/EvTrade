"""
t0.py — T0 一键买卖 + 配平系数 + 费率

设计：
- 配平系数 (t0_coefficient): 默认 1.0（按目标股数实买）
  - > 1.0: 超配（多买用于补卖单不足）
  - < 1.0: 减配（少买控制风险）
  - 0.0-0.99: 整股数 = floor(目标 * 系数 / 100) * 100
- T0 一键买: 根据目标股数自动取整到 100 股倍数
- T0 一键卖: 直接平仓所有可用

费率 (fee):
- commission_rate  默认 0.0001（万一）
- stamp_tax_rate   默认 0（无印花税）
- min_commission   默认 0（免五，无最低佣金）
- slippage         默认 0.001（滑点，备用）
- 手续费 = 佣金（买 + 卖），无印花税；费率从 sysconfig 读，见 sysconfig.get_fee_dict
- 真实已实现盈亏算法见 services.t0.aggregate_api.calc_realized_pnl
"""
from typing import Tuple

from server.db import db_session
from server.models.orm import Order
import logging

log = logging.getLogger(__name__)

# A 股最小交易单位
LOT_SIZE = 100


def get_fee_config() -> dict:
    """获取费率配置 (dict, 读 sysconfig)

    返回 dict 替代 ORM dict 对象, 调用方需调整字段访问:
    - cfg.commission_rate → cfg["commission_rate"]
    - cfg.stamp_tax_rate → cfg["stamp_tax_rate"]
    - cfg.min_commission  → cfg["min_commission"]
    - cfg.slippage        → cfg["slippage"]
    """
    from server.services.sysconfig import get_fee_dict
    return get_fee_dict()


def _fee_namespace():
    """向后兼容: 把 dict 转成 SimpleNamespace (cfg.x 写法兼容)."""
    from types import SimpleNamespace
    cfg = get_fee_config()
    return SimpleNamespace(**cfg)


def round_to_lot(volume: int, direction: str) -> int:
    """A 股整手向下取整（买）/ 向上取整（卖）

    买 1100 → 1100,  买 1050 → 1000
    卖 1100 → 1100,  卖 1050 → 1100
    """
    if volume <= 0:
        return 0
    if direction == "BUY":
        return (volume // LOT_SIZE) * LOT_SIZE
    elif direction == "SELL":
        return ((volume + LOT_SIZE - 1) // LOT_SIZE) * LOT_SIZE
    return volume


def calc_t0_volume(target_volume: int, coefficient: float, direction: str) -> int:
    """T0 配平：算最终要买/卖多少股

    Args:
        target_volume: 目标股数（来自前端）
        coefficient: 配平系数（默认 1.0）
        direction: BUY / SELL

    Returns:
        整手后的实际股数
    """
    if target_volume <= 0 or coefficient <= 0:
        return 0
    raw = target_volume * coefficient
    # 转 int（向下截断），然后整手
    vol = int(raw)
    return round_to_lot(vol, direction)


def calc_commission(amount: float, cfg: dict, direction: str) -> Tuple[float, float]:
    """算手续费 + 印花税（卖出）

    注：cfg dict 完整字段：
        commission_rate / stamp_tax_rate / min_commission / slippage
    min_commission 兜底逻辑在 services.t0.aggregate_api.calc_commission_and_tax 中实现，
    本函数保留原签名（不带 min 兜底）以兼容既有调用方。
    """
    commission = round(amount * cfg["commission_rate"], 2)
    stamp_tax = 0.0
    if direction == "SELL":
        stamp_tax = round(amount * cfg["stamp_tax_rate"], 2)
    return commission, stamp_tax


def calc_net_amount(price: float, volume: int, cfg: dict, direction: str) -> Tuple[float, float]:
    """算净成交金额（买方：含手续费；卖方：扣手续费+印花税）

    Returns: (gross_amount, net_amount)
        gross: 毛额
        net: 净额（实际增减资金）
    """
    gross = price * volume
    commission, stamp_tax = calc_commission(gross, cfg, direction)
    if direction == "BUY":
        net = gross + commission
    else:
        net = gross - commission - stamp_tax
    return round(gross, 2), round(net, 2)
