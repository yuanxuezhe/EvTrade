"""server.services.t0 — T0 交易统计模块

直接从以下路径导入（避免 __init__ 中介带来的开销）：
  from server.services.t0.core import calc_t0_volume, get_fee_config, ...
  from server.services.t0.fees import calc_commission_and_tax, ...
  from server.services.t0.pnl import calc_realized_pnl
  from server.services.t0.aggregators import aggregate_by_stock, ...
"""
# 兼容 from services.t0 import get_fee_config, calc_t0_volume, ...
# 这些会触发 ORM 注册（与测试的旧路径兼容）
from server.services.t0.core import (
    get_fee_config as get_fee_config,
    round_to_lot as round_to_lot,
    calc_t0_volume as calc_t0_volume,
    calc_commission as calc_commission,
    calc_net_amount as calc_net_amount,
    LOT_SIZE as LOT_SIZE,
)