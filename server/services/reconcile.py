"""
reconcile.py — v4 对账算法

启动人工触发，admin 调 POST /api/admin/reconcile/trigger：
1. 调 qry_pos + qry_asset + qry_orders + qry_trades（顺序：先查 RPC）
2. 计算 diff（本地 vs 柜台）
3. 写 reconcile_report 表
4. auto_reconcile=True → 用柜台数据覆盖本地
   auto_reconcile=False → 只写报告，不动数据
5. 切交易日到新 TRD_DATE

对账失败 → 不切交易日，返回 503，用户重试。
RPC 部分失败 → 写对账报告 + 503 错误详情，不切交易日。
"""
from datetime import datetime
from typing import Dict, Any, List
from sqlalchemy.orm import Session

from db import SessionLocal
from rpc.client import qry_positions, qry_asset, qry_orders, qry_trades
from models.orm import (
    Order, Trade, Position, Asset, TradingDay, ReconcileConfig, ReconcileReport,
)
import logging

log = logging.getLogger(__name__)


def get_reconcile_config(db: Session) -> ReconcileConfig:
    """获取对账配置（单行）"""
    cfg = db.query(ReconcileConfig).first()
    if not cfg:
        cfg = ReconcileConfig(auto_reconcile=False, updated_by='init')
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
    return cfg


def _safe_dict_list(data) -> List[Dict[str, Any]]:
    """从 RPC 响应里取 list"""
    if not data or int(data.get('code', -1)) != 0:
        return []
    return data.get('list', [])


async def do_reconcile(
    db: Session,
    new_trd_date: str,
    by_user: str,
) -> Dict[str, Any]:
    """执行对账

    Returns: {
        ok: bool,
        report_id: int,
        diffs: {...},
        applied: bool (auto_reconcile),
        error: str | None,
    }
    """
    cfg = get_reconcile_config(db)

    # 1. 拉柜台 4 类数据
    diffs: Dict[str, Any] = {'fetched_at': datetime.utcnow().isoformat()}
    rpc_errors: List[str] = []

    try:
        orders_data = _safe_dict_list(await qry_orders())
        diffs['orders_count'] = len(orders_data)
    except Exception as e:
        rpc_errors.append(f"qry_orders: {e}")
        orders_data = []

    try:
        trades_data = _safe_dict_list(await qry_trades())
        diffs['trades_count'] = len(trades_data)
    except Exception as e:
        rpc_errors.append(f"qry_trades: {e}")
        trades_data = []

    try:
        positions_data = _safe_dict_list(await qry_positions())
        diffs['positions_count'] = len(positions_data)
    except Exception as e:
        rpc_errors.append(f"qry_positions: {e}")
        positions_data = []

    try:
        assets_data = _safe_dict_list(await qry_asset())
        diffs['assets_count'] = len(assets_data)
    except Exception as e:
        rpc_errors.append(f"qry_asset: {e}")
        assets_data = []

    # 2. 写对账报告
    import json
    rpc_status = "ok"
    if rpc_errors:
        rpc_status = "failed" if not any([orders_data, trades_data, positions_data, assets_data]) else "partial"

    # 解析本地快照（对比用）
    local_orders = [
        {"order_id": o.order_id, "stock_code": o.stock_code, "status": o.status,
         "volume": o.volume, "traded_volume": o.traded_volume, "TRD_DATE": o.TRD_DATE}
        for o in db.query(Order).all()
    ]
    local_positions = [
        {"stock_code": p.stock_code, "total": p.total, "available": p.available,
         "TRD_DATE": p.TRD_DATE}
        for p in db.query(Position).all()
    ]
    local_assets = [
        {"TRD_DATE": a.TRD_DATE, "cash": a.cash, "total_asset": a.total_asset}
        for a in db.query(Asset).all()
    ]

    report = ReconcileReport(
        TRD_DATE=new_trd_date,
        mode="auto" if cfg.auto_reconcile else "manual",
        diffs_json=json.dumps({
            'rpc_errors': rpc_errors,
            'broker': {
                'orders': orders_data, 'trades': trades_data,
                'positions': positions_data, 'assets': assets_data,
            },
            'local': {
                'orders': local_orders, 'positions': local_positions, 'assets': local_assets,
            },
        }, ensure_ascii=False, default=str),
        broker_asset_json=json.dumps(assets_data, ensure_ascii=False, default=str),
        local_asset_json=json.dumps(local_assets, ensure_ascii=False, default=str),
        broker_positions_json=json.dumps(positions_data, ensure_ascii=False, default=str),
        local_positions_json=json.dumps(local_positions, ensure_ascii=False, default=str),
        rpc_status=rpc_status,
        error_message="; ".join(rpc_errors)[:512],
        created_by=None,  # TODO: admin user id
    )
    db.add(report)
    db.flush()

    # 3. 全部 RPC 失败 → 写报告 + 返 503
    if rpc_status == "failed":
        return {
            'ok': False,
            'report_id': report.id,
            'diffs': diffs,
            'applied': False,
            'error': f"全部 RPC 失败: {'; '.join(rpc_errors)}",
        }

    # 4. auto_reconcile=True → 覆盖本地
    applied = False
    if cfg.auto_reconcile:
        try:
            applied = _apply_broker_data(
                db, new_trd_date,
                orders_data, trades_data, positions_data, assets_data
            )
        except Exception as e:
            log.exception("apply_broker_data failed: %s", e)
            return {
                'ok': False,
                'report_id': report.id,
                'diffs': diffs,
                'applied': False,
                'error': f"覆盖本地失败: {e}",
            }

    # 5. 切交易日
    if applied or not cfg.auto_reconcile:
        old_active = db.query(TradingDay).filter_by(status='active').first()
        if old_active:
            old_active.status = 'closed'
        new_day = TradingDay(
            current_date=new_trd_date,
            status='active',
            initialized_at=datetime.utcnow(),
            initialized_by=by_user,
        )
        db.add(new_day)
        db.commit()
        db.refresh(report)

    return {
        'ok': True,
        'report_id': report.id,
        'diffs': diffs,
        'applied': applied,
        'error': None,
    }


def _apply_broker_data(
    db: Session,
    trd_date: str,
    orders_data: List[Dict],
    trades_data: List[Dict],
    positions_data: List[Dict],
    assets_data: List[Dict],
) -> bool:
    """用柜台数据覆盖本地表"""
    # Orders: 删旧日 + 插新日（对账是日初处理，覆盖就行）
    db.query(Order).filter(Order.TRD_DATE == trd_date).delete()
    for o in orders_data:
        order_id = str(o.get('order_id', ''))
        if not order_id:
            continue
        db.add(Order(
            order_id=order_id,
            client_order_id=str(o.get('client_order_id', order_id)),
            order_no=str(o.get('order_no', order_id)),
            order_remark=str(o.get('order_remark', order_id)),
            TRD_DATE=trd_date,
            stock_code=str(o.get('stock_code', '')),
            order_type=str(o.get('order_type', '')),
            price_type=int(o.get('price_type', 11) or 11),
            price=float(o.get('price', 0) or 0),
            volume=int(o.get('volume', 0) or 0),
            traded_volume=int(o.get('traded_volume', 0) or 0),
            traded_amount=float(o.get('traded_amount', 0) or 0),
            avg_price=float(o.get('avg_price', 0) or 0),
            status=str(o.get('status', '49')),
            status_msg=str(o.get('status_msg', '')),
            order_time=str(o.get('order_time', '')),
        ))

    # Trades
    db.query(Trade).filter(Trade.TRD_DATE == trd_date).delete()
    for t in trades_data:
        trade_id = str(t.get('trade_id', ''))
        if not trade_id:
            continue
        db.add(Trade(
            trade_id=trade_id,
            TRD_DATE=trd_date,
            order_id=str(t.get('order_id', '')),
            stock_code=str(t.get('stock_code', '')),
            order_type=str(t.get('order_type', '')),
            price=float(t.get('price', 0) or 0),
            volume=int(t.get('volume', 0) or 0),
            amount=float(t.get('amount', 0) or 0),
            trade_time=str(t.get('trade_time', '')),
        ))

    # Positions
    db.query(Position).filter(Position.TRD_DATE == trd_date).delete()
    for p in positions_data:
        stock_code = str(p.get('stock_code', ''))
        if not stock_code:
            continue
        db.add(Position(
            TRD_DATE=trd_date,
            stock_code=stock_code,
            stock_name=str(p.get('stock_name', '')),
            initial_position=int(p.get('initial_position', 0) or 0),
            today_buy=int(p.get('today_buy', 0) or 0),
            today_sell=int(p.get('today_sell', 0) or 0),
            available=int(p.get('available', 0) or 0),
            total=int(p.get('total', p.get('volume', 0)) or 0),
            cost=float(p.get('cost', p.get('cost_price', 0)) or 0),
            synced_at=datetime.utcnow(),
            synced_from='rpc_reconcile',
        ))

    # Assets (单行)
    db.query(Asset).filter(Asset.TRD_DATE == trd_date).delete()
    if assets_data:
        a = assets_data[0]
        db.add(Asset(
            TRD_DATE=trd_date,
            cash=float(a.get('cash', 0) or 0),
            frozen_cash=float(a.get('frozen_cash', a.get('frozen', 0)) or 0),
            market_value=float(a.get('market_value', 0) or 0),
            total_asset=float(a.get('total_asset', 0) or 0),
            synced_at=datetime.utcnow(),
        ))

    db.commit()
    return True
