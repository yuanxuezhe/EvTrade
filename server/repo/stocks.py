"""
repo/stocks.py — 股票基础信息 CRUD (v23 slim-stocks-table, v46+ short-name-auto)

职责:
- upsert:增量更新(7 天内跳过),crawler 自动入仓用
- get_by_code:按代码查(前端展示用)
- list_all:全表(同步任务遍历用)
- list_codes:仅返回 stock_code 列表(轻量)
- update_by_admin:admin 手动编辑 stocks 字段(白名单, stock_name 改动自动重算 short_name)
- create_by_admin:admin 手动添加(自动生成 short_name, REQ-STOCK-007)
- to_dict:ORM → dict(WS 推送用)
- to_dict_from_data:raw dict (来自 crawler) → 标准 dict (WS 推送用)

字段精简历史:
- v21 (2026-07-10) stock-info-crawler: 14 个业务字段(基础信息 + 公司简介)
- v23 (2026-07-12) slim-stocks-table: 6 个业务字段(基础信息 + 交易粒度)
- v25 (2026-07-12) stocks-cache-and-short-name: +short_name 字段(7 字段)
- v46+ (2026-07-15) short-name-auto: short_name 改为自动生成, admin 无需传 (REQ-STOCK-007)
  历史 14 字段数据保留在 stocks_legacy 表
"""
from datetime import datetime, timedelta
from typing import List, Optional, Dict
import threading

from sqlalchemy.orm import Session

from server.models.orm import Stock
from server.services.short_name import to_short_name  # v46+ REQ-STOCK-007


# 增量 upsert 的"7 天内跳过"阈值
SKIP_THRESHOLD_DAYS = 7

# v78.3: 内存 cache (key: stock_code, value: is_t0_able bool)
# push handler 频繁调用 (trd_cfm 每笔成交都查), 加 cache 避免每次打 DB
# v80: 扩展为 {is_t0_able, scale, stktype} 三字段 dict (下单价格精度用)
_stock_cache: Dict[str, Dict] = {}  # code -> {"t0": bool, "scale": int, "stktype": int}
_stock_cache_loaded: bool = False
_stock_cache_lock = threading.RLock()


def _ensure_cache_shape(d: Dict) -> Dict:
    """兼容老 cache dict 形态 (v78.3 只有 is_t0_able)."""
    if "scale" not in d:
        d["scale"] = 2
    if "stktype" not in d:
        d["stktype"] = 0
    if "t0" not in d and "is_t0_able" in d:
        d["t0"] = d["is_t0_able"]
    elif "t0" not in d:
        d["t0"] = False
    return d


def get_is_t0_able(db: Session, stock_code: str) -> bool:
    """v78.3: 从内存 cache 读 is_t0_able; cache miss 时回退 DB 并填 cache

    设计: trade_cfm 推送每笔成交都会查, DB query 频繁;
    cache 简化路径 = O(1) 读. 启动时 init_db 同步调用 load_all_stocks 一次.
    admin 更新股票时通过 invalidate_stock_cache() 失效对应 key.
    """
    if not stock_code:
        return False
    with _stock_cache_lock:
        if _stock_cache_loaded and stock_code in _stock_cache:
            return _stock_cache[stock_code].get("t0", False)
        # cache miss → DB 查询
        row = db.query(Stock).filter_by(stock_code=stock_code).first()
        if row is None:
            return False
        result = {
            "t0": bool(row.is_t0_able),
            "scale": int(getattr(row, "scale", 2) or 2),
            "stktype": int(getattr(row, "stktype", 0) or 0),
        }
        _stock_cache[stock_code] = result
        return result["t0"]


def get_stock_scale(db: Session, stock_code: str) -> int:
    """v80: 读 stock.scale (价格小数位精度). cache miss 走 DB."""
    if not stock_code:
        return 2
    with _stock_cache_lock:
        if _stock_cache_loaded and stock_code in _stock_cache:
            return _stock_cache[stock_code].get("scale", 2)
        row = db.query(Stock).filter_by(stock_code=stock_code).first()
        if row is None:
            return 2
        return int(getattr(row, "scale", 2) or 2)


def get_stock_stktype(db: Session, stock_code: str) -> int:
    """v80: 读 stock.stktype (0=股票/1=ETF). cache miss 走 DB."""
    if not stock_code:
        return 0
    with _stock_cache_lock:
        if _stock_cache_loaded and stock_code in _stock_cache:
            return _stock_cache[stock_code].get("stktype", 0)
        row = db.query(Stock).filter_by(stock_code=stock_code).first()
        if row is None:
            return 0
        return int(getattr(row, "stktype", 0) or 0)


def load_all_stocks(db: Session) -> int:
    """v78.3: 启动时一次性加载所有 stocks.is_t0_able 到内存 cache
    v80: 扩展加载 scale + stktype (下单价格精度 + 可交易类型校验用)

    返回加载条目数. 与 sysconfig._ensure_defaults 类似, 在 init_db 末尾调用.
    """
    global _stock_cache_loaded
    rows = db.query(
        Stock.stock_code, Stock.is_t0_able, Stock.scale, Stock.stktype
    ).all()
    with _stock_cache_lock:
        _stock_cache.clear()
        for code, t0, scale, stktype in rows:
            _stock_cache[code] = {
                "t0": bool(t0),
                "scale": int(scale or 2),
                "stktype": int(stktype or 0),
            }
        _stock_cache_loaded = True
    return len(rows)


def invalidate_stock_cache(stock_code: str = "") -> None:
    """v78.3: 失效 cache (admin 编辑或新增 stock 时调用)
    v80: 同时清掉 scale + stktype 缓存
    """
    global _stock_cache_loaded
    with _stock_cache_lock:
        if stock_code:
            _stock_cache.pop(stock_code, None)
        else:
            _stock_cache.clear()
            _stock_cache_loaded = False


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
    """admin 显式编辑 stocks 表(REQ-STOCK-003 + REQ-STOCK-007)

    与 upsert 的区别:
    - upsert 是爬虫自动入仓,7 天阈值跳过
    - update_by_admin 是 admin 手动改,无阈值,白名单字段全覆盖

    v46+: 若 stock_name 字段在 data 中被修改, 自动重算 short_name (REQ-STOCK-007)
          data 中若含 short_name 也会被忽略 (admin 无权改)
    """
    existing = db.query(Stock).filter_by(stock_code=stock_code).first()
    if existing is None:
        return None

    # v46+: 检测 stock_name 变化, 若变则重算 short_name
    new_short_name = None
    if 'stock_name' in data:
        new_short_name = to_short_name(data['stock_name'])

    for k, v in data.items():
        # v46+: 忽略 admin 传入的 short_name 字段
        if k == 'short_name':
            continue
        if k in _ADMIN_EDITABLE_FIELDS and hasattr(existing, k):
            setattr(existing, k, v)

    # v46+: 应用重算后的 short_name
    if new_short_name is not None:
        existing.short_name = new_short_name

    db.commit()
    db.refresh(existing)
    return existing


def create_by_admin(db: Session, data: Dict) -> Optional[Stock]:
    """admin 手动添加 stocks 行(REQ-STOCK-006 + REQ-STOCK-007)

    与 upsert 的区别:
    - upsert 是爬虫自动入仓,7 天阈值跳过
    - create_by_admin 是 admin 手动新增,无阈值,stock_code 必填且必须不存在

    v46+: short_name 由 stock_name 自动派生 (REQ-STOCK-007)
          data 中若含 short_name 会被忽略 (admin 无权传)
    """
    stock_code = data.get('stock_code')
    if not stock_code:
        return None  # API 层会在 Pydantic 阶段拦截(必填字段)

    # 重复检查(API 层会基于 None 返 409)
    existing = db.query(Stock).filter_by(stock_code=stock_code).first()
    if existing is not None:
        return None

    # 只允许白名单字段,stock_code 单独处理;v46+ 排除 short_name (自动生成)
    payload = {k: v for k, v in data.items()
               if k in _ADMIN_EDITABLE_FIELDS and hasattr(Stock, k) and k != 'short_name'}
    # v46+: 自动生成 short_name (来自 stock_name)
    payload['short_name'] = to_short_name(data.get('stock_name', ''))

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
    """ORM → dict(WS 推送前端用, v23 字段精简, v25 加 short_name, v80 加 scale + stktype)"""
    return {
        'stock_code': stock.stock_code,
        'stock_name': stock.stock_name or '',
        'sector': stock.sector,
        'is_t0_able': bool(stock.is_t0_able),
        'min_buy_qty': stock.min_buy_qty,
        'trade_unit': stock.trade_unit,
        'short_name': stock.short_name,
        'stktype': int(getattr(stock, 'stktype', 0) or 0),  # v80
        'scale': int(getattr(stock, 'scale', 2) or 2),      # v80
    }


def to_dict_from_data(stock_code: str, data: Dict) -> Dict:
    """raw dict (来自 crawler) → 标准 dict (WS 推送用, v23 字段精简, v25 加 short_name, v80 加 scale + stktype)

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
        'stktype': int(data.get('stktype', 0) or 0),  # v80
        'scale': int(data.get('scale', 2) or 2),      # v80
    }