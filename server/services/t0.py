"""
t0.py — T0 一键买卖 + 配平系数 + 费率

设计：
- 配平系数 (t0_coefficient): 默认 1.0（按目标股数实买）
  - > 1.0: 超配（多买用于补卖单不足）
  - < 1.0: 减配（少买控制风险）
  - 0.0-0.99: 整股数 = floor(目标 * 系数 / 100) * 100
- T0 一键买: 根据目标股数自动取整到 100 股倍数
- T0 一键卖: 直接平仓所有可用

费率 (fee) — v7 schema 后 ORM 完整字段：
- commission_rate  默认 0.0001（万一）
- stamp_tax_rate   默认 0.001（卖出千 1）
- min_commission   默认 5.0（A 股规则：佣金 < 5 元按 5 元收）
- slippage         默认 0.001（滑点，备用）
- 真实已实现盈亏算法见 services.t0_aggregate.calc_realized_pnl
"""
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from typing import Optional, Tuple

from server.db import SessionLocal
from server.models.orm import FeeConfig
import logging

log = logging.getLogger(__name__)

# A 股最小交易单位
LOT_SIZE = 100


def get_fee_config() -> FeeConfig:
    """获取费率配置（单行）"""
    db = SessionLocal()
    try:
        cfg = db.query(FeeConfig).first()
        if not cfg:
            cfg = FeeConfig(
                commission_rate=0.0001,
                stamp_tax_rate=0.001,  # 卖出印花税千 1
                min_commission=5.0,    # A 股最低佣金 5 元
                slippage=0.001,
            )
            db.add(cfg)
            db.commit()
            db.refresh(cfg)
        return cfg
    finally:
        db.close()


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


def calc_commission(amount: float, cfg: FeeConfig, direction: str) -> Tuple[float, float]:
    """算手续费 + 印花税（卖出）

    注：v7 schema 后 ORM FeeConfig 完整字段：
        commission_rate / stamp_tax_rate / min_commission / slippage
    min_commission 兜底逻辑在 services.t0_aggregate.calc_commission_and_tax 中实现，
    本函数保留原签名（不带 min 兜底）以兼容既有调用方。
    """
    commission = round(amount * cfg.commission_rate, 2)
    stamp_tax = 0.0
    if direction == "SELL":
        stamp_tax = round(amount * cfg.stamp_tax_rate, 2)
    return commission, stamp_tax


def calc_net_amount(price: float, volume: int, cfg: FeeConfig, direction: str) -> Tuple[float, float]:
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
