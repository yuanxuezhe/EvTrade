"""
repo/stocks.py — 股票基础信息 CRUD (v23 slim-stocks-table)

职责:
- upsert:增量更新(7 天内跳过),crawler 自动入仓用
- get_by_code:按代码查(前端展示用)
- list_all:全表(同步任务遍历用)
- list_codes:仅返回 stock_code 列表(轻量)
- update_by_admin:admin 手动编辑 stocks 字段(白名单)
- to_dict:ORM → dict(WS 推送用)
- to_dict_from_data:raw dict (来自 crawler) → 标准 dict (WS 推送用)

字段精简历史:
- v21 (2026-07-10) stock-info-crawler: 14 个业务字段(基础信息 + 公司简介)
- v23 (2026-07-12) slim-stocks-table: 6 个业务字段(基础信息 + 交易粒度)
  历史 14 字段数据保留在 stocks_legacy 表
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
        data: dict 含 stock_name/sector(其余字段白名单过滤)
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


# v23 slim-stocks-table: admin 显式编辑 stocks 行
# v25 stocks-cache-and-short-name: +short_name (6 → 7 字段)
# 允许覆盖的字段白名单（stock_code 是 PK,created_at/updated_at 由 DB 维护）
# 7 字段:stock_name/sector/is_t0_able/min_buy_qty/trade_unit/short_name
_ADMIN_EDITABLE_FIELDS = (
    'stock_name', 'sector',
    'is_t0_able', 'min_buy_qty', 'trade_unit',
    'short_name',
)


def update_by_admin(db: Session, stock_code: str, data: Dict) -> Optional[Stock]:
    """admin 显式编辑 stocks 表(REQ-STOCK-003)

    与 upsert 的区别:
    - upsert 是爬虫自动入仓,7 天阈值跳过
    - update_by_admin 是 admin 手动改,无阈值,白名单字段全覆盖

    Args:
        db: SQLAlchemy Session
        stock_code: PK
        data: dict,只接受白名单内字段

    Returns:
        更新后的 Stock ORM 对象,或 None(stock_code 不存在)
    """
    existing = db.query(Stock).filter_by(stock_code=stock_code).first()
    if existing is None:
        return None
    for k, v in data.items():
        if k in _ADMIN_EDITABLE_FIELDS and hasattr(existing, k):
            setattr(existing, k, v)
    db.commit()
    db.refresh(existing)
    return existing


def create_by_admin(db: Session, data: Dict) -> Optional[Stock]:
    """admin 手动添加 stocks 行(REQ-STOCK-006)

    与 upsert 的区别:
    - upsert 是爬虫自动入仓,7 天阈值跳过
    - create_by_admin 是 admin 手动新增,无阈值,stock_code 必填且必须不存在

    Args:
        db: SQLAlchemy Session
        data: dict,必含 stock_code;其余字段走白名单 _ADMIN_EDITABLE_FIELDS 过滤

    Returns:
        新插入的 Stock ORM 对象,或 None(stock_code 已存在 → API 层抛 409)
    """
    stock_code = data.get('stock_code')
    if not stock_code:
        return None  # API 层会在 Pydantic 阶段拦截(必填字段)

    # 重复检查(API 层会基于 None 返 409)
    existing = db.query(Stock).filter_by(stock_code=stock_code).first()
    if existing is not None:
        return None

    # 只允许白名单字段,stock_code 单独处理
    payload = {k: v for k, v in data.items()
               if k in _ADMIN_EDITABLE_FIELDS and hasattr(Stock, k)}
    stock = Stock(stock_code=stock_code, **payload)
    db.add(stock)
    db.commit()
    db.refresh(stock)
    return stock


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
    """ORM → dict(WS 推送前端用, v23 字段精简, v25 加 short_name)"""
    return {
        'stock_code': stock.stock_code,
        'stock_name': stock.stock_name or '',
        'sector': stock.sector,
        'is_t0_able': bool(stock.is_t0_able),
        'min_buy_qty': stock.min_buy_qty,
        'trade_unit': stock.trade_unit,
        'short_name': stock.short_name,
    }


def to_dict_from_data(stock_code: str, data: Dict) -> Dict:
    """raw dict (来自 crawler) → 标准 dict (WS 推送用, v23 字段精简, v25 加 short_name)

    用于 upsert 成功后立即推 stock_synced,无需再读 DB
    """
    return {
        'stock_code': stock_code,
        'stock_name': data.get('stock_name', ''),
        'sector': data.get('sector'),
        'is_t0_able': bool(data.get('is_t0_able', False)),
        'min_buy_qty': int(data.get('min_buy_qty', 100)),
        'trade_unit': int(data.get('trade_unit', 1)),
        'short_name': data.get('short_name'),
    }