"""
push_handler_ast.py — ast_cfm 处理（v10: broker 原字段名）

行为：
- 单行资产表覆盖
- 写入 total_asset / cash / frozen_cash / market_value
- v10 字段对齐：读 broker 原字段 `frozen_cash`（之前 alias `frozen`），加 `account_id` 透传
"""
from typing import Any, Dict

from sqlalchemy.orm import Session

from server.models.orm import Asset
from server.services.push_helpers import _float, _utcnow


def handle_ast_cfm(db: Session, row: Dict[str, Any], ts: str) -> None:
    """处理 ast_cfm 推送

    柜台字段（v10 broker 原字段名，权威源: iquant/xtquant_api.py 第 168-181 行）:
      account_id     账号                                v10 透传
      total_asset    总资产
      cash           现金
      frozen_cash    冻结                                v10 原字段名
      market_value   持仓市值
    """
    asset = db.query(Asset).first()
    if not asset:
        asset = Asset()
        db.add(asset)

    asset.total_asset = _float(row.get('total_asset', 0))
    asset.cash = _float(row.get('cash', 0))
    asset.frozen_cash = _float(row.get('frozen_cash', 0))  # v10: 原字段名
    asset.market_value = _float(row.get('market_value', 0))
    asset.synced_at = _utcnow()
    asset.synced_from = 'push_ast_cfm'

    print("[ast_cfm] updated total={} cash={}".format(asset.total_asset, asset.cash))
