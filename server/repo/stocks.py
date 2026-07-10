"""
repo/stocks.py — 股票基础信息 CRUD (v21 stock-info-crawler)

职责:
- upsert:增量更新(7 天内跳过)
- get_by_code:按代码查(前端展示用)
- list_by_industry:按行业筛选(前端选股用)
- list_all:全表(同步任务遍历用)
- list_codes:仅返回 stock_code 列表(轻量)
- to_dict:ORM → dict(WS 推送用)
"""
from datetime import datetime, timedelta
from typing import List, Optional, Dict

from sqlalchemy.orm import Session

from server.models.orm import Stock


# 增量 upsert 的"7 天内跳过"阈值
SKIP_THRESHOLD_DAYS = 7


def upsert(db: Session, stock_code: str, data: Dict) -> str:
    """增量 upsert stocks 表(REQ-STOCK-002)

    Args:
        db: SQLAlchemy Session
        stock_code: '000001.SZ'
        data: dict 含 stock_name/industry/sector/market/intro/...
              (data 里若有 stock_code 会被剔除,以参数 stock_code 为准)

    Returns:
        'inserted' | 'updated' | 'skipped'
        - inserted: 新行(刚插入)
        - updated: 已存在 + 距上次更新 > 7 天 → 覆盖所有业务字段
        - skipped: 已存在 + 距上次更新 ≤ 7 天 → 跳过
    """
    # data 可能有 stock_code 字段,剔除(参数 stock_code 为准)
    payload = {k: v for k, v in data.items() if k != 'stock_code'}
    existing = db.query(Stock).filter_by(stock_code=stock_code).first()
    if existing is None:
        # INSERT
        stock = Stock(stock_code=stock_code, **payload)
        db.add(stock)
        db.commit()
        return 'inserted'
    # 已存在 → 检查 7 天阈值
    if existing.updated_at and existing.updated_at > (datetime.utcnow() - timedelta(days=SKIP_THRESHOLD_DAYS)):
        return 'skipped'
    # UPDATE
    for k, v in payload.items():
        if hasattr(existing, k):
            setattr(existing, k, v)
    db.commit()
    return 'updated'


def get_by_code(db: Session, stock_code: str) -> Optional[Stock]:
    return db.query(Stock).filter_by(stock_code=stock_code).first()


def list_by_industry(db: Session, industry: str) -> List[Stock]:
    return db.query(Stock).filter_by(industry=industry).order_by(Stock.stock_code).all()


def list_all(db: Session, limit: Optional[int] = None) -> List[Stock]:
    q = db.query(Stock).order_by(Stock.stock_code)
    if limit:
        q = q.limit(limit)
    return q.all()


def list_codes(db: Session) -> List[str]:
    """仅返回 stock_code 列表,用于同步任务遍历"""
    rows = db.query(Stock.stock_code).order_by(Stock.stock_code).all()
    return [r[0] for r in rows]


def to_dict(stock: Stock) -> Dict:
    """ORM → dict(WS 推送前端用)"""
    return {
        'stock_code': stock.stock_code,
        'stock_name': stock.stock_name or '',
        'industry': stock.industry,
        'sector': stock.sector,
        'market': stock.market,
        'list_date': stock.list_date.isoformat() if stock.list_date else None,
        'total_share': stock.total_share,
        'float_share': stock.float_share,
        'market_cap': float(stock.market_cap or 0.0),
        'pe_ratio': float(stock.pe_ratio) if stock.pe_ratio is not None else None,
        'pb_ratio': float(stock.pb_ratio) if stock.pb_ratio is not None else None,
        'intro': stock.intro or '',
    }


def to_dict_from_data(stock_code: str, data: Dict) -> Dict:
    """raw dict (来自 crawler) → 标准 dict (WS 推送用)

    用于 upsert 成功后立即推 stock_synced,无需再读 DB
    """
    return {
        'stock_code': stock_code,
        'stock_name': data.get('stock_name', ''),
        'industry': data.get('industry'),
        'sector': data.get('sector'),
        'market': data.get('market'),
        'list_date': data.get('list_date'),
        'total_share': data.get('total_share', 0),
        'float_share': data.get('float_share', 0),
        'market_cap': float(data.get('market_cap') or 0.0),
        'pe_ratio': data.get('pe_ratio'),
        'pb_ratio': data.get('pb_ratio'),
        'intro': data.get('intro') or '',
    }