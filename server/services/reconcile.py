"""
reconcile.py — v5 对账算法 (schema refactor: trading_day→sys_status, 字段重命名)

启动人工触发，admin 调 POST /api/admin/reconcile/trigger：
1. 调 qry_positions + qry_asset（仅 2 个 RPC，委托/成交靠 push 增量）
2. 计算 diff（本地 vs 柜台）
3. 写 reconcile_report 表
4. auto_reconcile=True → 用柜台数据覆盖本地 Position + Asset
   auto_reconcile=False → 只写报告，不动数据
5. 切交易日到新 trd_date（写入 sys_status 表）

对账失败 → 不切交易日，返回 503，用户重试。
RPC 部分失败 → 写对账报告 + 503 错误详情，不切交易日。

v5 改动（schema refactor）：
- TradingDay → SysStatus；current_date → trd_date
- Position 字段：initial_position→last_vol, available→avl_vol, total→vol, cost→cost_price
- Asset 去 TRD_DATE，单行无主键
- ReconcileReport 复合主键 (trd_date, mode, created_at)
"""
from datetime import datetime, timezone
from typing import Dict, Any, List
from sqlalchemy.orm import Session

from server.db import SessionLocal
from server.rpc.client import qry_positions, qry_asset
from server.models.orm import (
    Position, Asset, SysStatus, ReconcileConfig, ReconcileReport,
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

    NOTE: report_id 在 v5 改为 (trd_date, mode, created_at) 复合键，
    返回中只取 created_at 作为标识。
    """
    cfg = get_reconcile_config(db)

    # 1. 拉柜台 2 类数据 (委托/成交靠 push 增量, 不在对账走)
    diffs: Dict[str, Any] = {'fetched_at': datetime.now(timezone.utc).replace(tzinfo=None).isoformat()}
    rpc_errors: List[str] = []

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
        rpc_status = "failed" if not any([positions_data, assets_data]) else "partial"

    # 解析本地快照（对比用; 委托/成交不参与对账）
    local_positions = [
        {"stock_code": p.stock_code, "vol": p.vol, "avl_vol": p.avl_vol,
         "cost_price": p.cost_price}
        for p in db.query(Position).all()
    ]
    local_assets = [
        {"cash": a.cash, "total_asset": a.total_asset}
        for a in db.query(Asset).all()
    ]

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    report = ReconcileReport(
        trd_date=new_trd_date,
        mode="auto" if cfg.auto_reconcile else "manual",
        created_at=now,
        diffs_json=json.dumps({
            'rpc_errors': rpc_errors,
            'broker': {
                'positions': positions_data, 'assets': assets_data,
            },
            'local': {
                'positions': local_positions, 'assets': local_assets,
            },
        }, ensure_ascii=False, default=str),
        broker_asset_json=json.dumps(assets_data, ensure_ascii=False, default=str),
        local_asset_json=json.dumps(local_assets, ensure_ascii=False, default=str),
        broker_positions_json=json.dumps(positions_data, ensure_ascii=False, default=str),
        local_positions_json=json.dumps(local_positions, ensure_ascii=False, default=str),
        rpc_status=rpc_status,
        error_message="; ".join(rpc_errors)[:512],
        created_by=int(by_user) if by_user else None,
    )
    db.add(report)
    db.flush()

    # 3. 全部 RPC 失败 → 写报告 + 返 503
    if rpc_status == "failed":
        return {
            'ok': False,
            'report_id': int(now.timestamp()),
            'diffs': diffs,
            'applied': False,
            'error': f"全部 RPC 失败: {'; '.join(rpc_errors)}",
        }

    # 4. auto_reconcile=True → 覆盖本地 (Position + Asset, 委托/成交跳过)
    applied = False
    if cfg.auto_reconcile:
        try:
            applied = _apply_broker_data(
                db, new_trd_date,
                positions_data, assets_data
            )
        except Exception as e:
            log.exception("apply_broker_data failed: %s", e)
            return {
                'ok': False,
                'report_id': int(now.timestamp()),
                'diffs': diffs,
                'applied': False,
                'error': f"覆盖本地失败: {e}",
            }

    # 5. 切交易日 (upsert: 有则激活老行, 无则新增)
    #
    # DB 层级: SysStatus ORM 主键 trd_date
    # 防同日多 INSERT, 配合本 upsert 块保证同日只 1 行 active。
    # 同 trd_date 再次 init: 走 `existing` 分支, status='active' + 更新元数据
    # 切到新日: 老的 active 同 trd_date 不同的先 closed, 再查/插新日
    if applied or not cfg.auto_reconcile:
        old_active = db.query(SysStatus).filter_by(status='active').first()
        if old_active and old_active.trd_date != new_trd_date:
            old_active.status = 'closed'
        existing = db.query(SysStatus).filter_by(trd_date=new_trd_date).first()
        if existing:
            existing.status = 'active'
            existing.initialized_at = now
            existing.initialized_by = by_user
        else:
            db.add(SysStatus(
                trd_date=new_trd_date,
                status='active',
                initialized_at=now,
                initialized_by=by_user,
            ))
        db.commit()

    return {
        'ok': True,
        'report_id': int(now.timestamp()),
        'diffs': diffs,
        'applied': applied,
        'error': None,
    }


def _apply_broker_data(
    db: Session,
    trd_date: str,
    positions_data: List[Dict],
    assets_data: List[Dict],
) -> bool:
    """用柜台数据覆盖本地 (仅 Position + Asset, 委托/成交靠 push)

    v5 简化: 委托/成交不在对账流程处理, 改靠 push_handlers.handle_push
    (ord_cfm / trd_cfm 事件) 自动 upsert 到本地表。
    """
    # Positions: 按 stock_code PK 全表覆盖
    # change consolidate-position-data-flow: parser 输出 dict 键名已与 Position ORM 列名对齐
    # (broker wire 字段 volume/avl_amt/avg_price/market_value 在 _parse_positions 边界已完成重命名/丢弃)
    db.query(Position).delete()
    for p in positions_data:
        stock_code = str(p.get('stock_code', ''))
        if not stock_code:
            continue
        db.add(Position(
            stock_code=stock_code,
            stock_name=str(p.get('stock_name', '')),
            last_vol=int(p.get('last_vol', 0) or 0),
            today_buy=int(p.get('today_buy', 0) or 0),
            today_sell=int(p.get('today_sell', 0) or 0),
            avl_vol=int(p.get('avl_vol', 0) or 0),
            vol=int(p.get('vol', 0) or 0),
            cost_price=float(p.get('cost_price', 0) or 0),
            synced_at=datetime.now(timezone.utc).replace(tzinfo=None),
            synced_from='rpc_reconcile',
        ))

    # Assets: 单行；Asset ORM 无主键，先清空再写入
    # Asset broker 字段名已与 DB 列名一致 (cash/frozen_cash/market_value/total_asset),
    # 无需 remap。
    db.query(Asset).delete()
    if assets_data:
        a = assets_data[0]
        db.add(Asset(
            cash=float(a.get('cash', 0) or 0),
            frozen_cash=float(a.get('frozen_cash', 0) or 0),
            market_value=float(a.get('market_value', 0) or 0),
            total_asset=float(a.get('total_asset', 0) or 0),
            synced_at=datetime.now(timezone.utc).replace(tzinfo=None),
            synced_from='rpc_reconcile',
        ))

    db.commit()
    return True
