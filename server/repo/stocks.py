"""
repo/stocks.py - 股票基础信息 CRUD (v23 slim-stocks-table, v46+ short-name-auto, v80.5 tables, v90 去 _stock_cache)

职责:
- upsert:增量更新(7 天内跳过),crawler 自动入仓用
- get_by_code:按代码查(前端展示用)
- list_all:全表(同步任务遍历用)
- list_codes:仅返回 stock_code 列表(轻量)
- update_by_admin:admin 手动编辑 stocks 字段(白名单, stock_name 改动自动重算 short_name)
- create_by_admin:admin 手动添加(自动生成 short_name, REQ-STOCK-007)
- to_dict:Row -> dict(API 响应用)
- to_dict_from_data:raw dict (来自 crawler) -> 标准 dict
- GetStockInfo / get_is_t0_able / get_stock_scale / get_stock_stktype: 证券元信息查询 (v90 直查 DB)

字段精简历史:
- v21 (2026-07-10) stock-info-crawler: 14 个业务字段(基础信息 + 公司简介)
- v23 (2026-07-12) slim-stocks-table: 6 个业务字段(基础信息 + 交易粒度)
- v25 (2026-07-12) stocks-cache-and-short-name: +short_name 字段(7 字段)
- v46+ (2026-07-15) short-name-auto: short_name 改为自动生成, admin 无需传 (REQ-STOCK-007)
- v90 (2026-07-23): 去掉 _stock_cache 内存缓存, 改为直查 DB; 缓存职责移至前端 IndexedDB
"""
from datetime import datetime, timedelta
from typing import List, Optional, Dict

from server.services.short_name import to_short_name  # v46+ REQ-STOCK-007
from server.tables.base import Row
from server.tables.stocks import Stocks


# 增量 upsert 的"7 天内跳过"阈值
SKIP_THRESHOLD_DAYS = 7


# ============================================================================
# v90: 证券信息查询入口 - 直查 DB (去 _stock_cache, 前端 IndexedDB 负责缓存)
# ============================================================================
def GetStockInfo(stock_code: str) -> dict:
    """获取证券元信息 (v90 去缓存版, 直查 DB)

    Args:
        stock_code: '000001.SZ'

    Returns:
        dict: {
            "stktype": int,   # 0=股票 / 1=ETF
            "scale": int,     # 价格小数位 (默认 2, ETF 可为 3)
            "t0": bool,       # 是否支持 T+0
        }

    关联函数:
        - place_order: 用 stktype 校验可交易类型
        - push ord/trd: 用 scale round 价格字段
        - trd_cfm: 用 t0 判断做T标记
    """
    if not stock_code:
        return {"stktype": 0, "scale": 2, "t0": False}
    row = Stocks.query_one(stock_code=stock_code)
    if row is None:
        return {"stktype": 0, "scale": 2, "t0": False}
    return {
        "stktype": int(row.stktype or 0),
        "scale": int(row.scale or 2),
        "t0": bool(row.is_t0_able),
    }


def get_is_t0_able(db=None, stock_code: str = "") -> bool:
    """读 stock.is_t0_able (v90 直查 DB)"""
    return GetStockInfo(stock_code)["t0"]


def get_stock_scale(db=None, stock_code: str = "") -> int:
    """读 stock.scale (v90 直查 DB)"""
    return GetStockInfo(stock_code)["scale"]


def get_stock_stktype(db=None, stock_code: str = "") -> int:
    """读 stock.stktype (v90 直查 DB)"""
    return GetStockInfo(stock_code)["stktype"]


def upsert(db=None, stock_code: str = "", data: Optional[Dict] = None) -> str:
    """增量 upsert stocks 表(REQ-STOCK-002)

    Args:
        db: 兼容旧调用方的保留参数, v80.5 不再使用
        stock_code: '000001.SZ'
        data: dict 含 stock_name/sector(其余字段白名单过滤)
              (data 里若有 stock_code 会被剔除,以参数 stock_code 为准)

    Returns:
        'inserted' | 'updated' | 'skipped'
        - inserted: 新行(刚插入)
        - updated: 已存在 + 距上次更新 > 7 天 -> 覆盖所有业务字段
        - skipped: 已存在 + 距上次更新 ≤ 7 天 -> 跳过
    """
    # data 可能有 stock_code 字段,剔除(参数 stock_code 为准)
    payload = {k: v for k, v in (data or {}).items() if k != 'stock_code'}
    existing = Stocks.query_one(stock_code=stock_code)

    # 已存在 -> 检查 7 天阈值
    if existing is not None and existing.updated_at and existing.updated_at > (datetime.utcnow() - timedelta(days=SKIP_THRESHOLD_DAYS)):
        return 'skipped'

    # 原生 ON DUPLICATE KEY UPDATE (一行搞定 INSERT or UPDATE)
    update_data = {k: v for k, v in payload.items() if existing is None or hasattr(existing, k)}
    Stocks.upsert_one({'stock_code': stock_code, **update_data}, return_row=False)
    return 'inserted' if existing is None else 'updated'


def get_by_code(db=None, stock_code: str = "") -> Optional[Row]:
    """按 stock_code 主键查询; db 参数仅为兼容旧调用方保留."""
    return Stocks.query_one(stock_code=stock_code)


# v23 slim-stocks-table: admin 显式编辑 stocks 行
# v25 stocks-cache-and-short-name: +short_name (6 -> 7 字段)
# 允许覆盖的字段白名单（stock_code 是 PK,created_at/updated_at 由 DB 维护）
# 8 字段:stock_name/sector/is_t0_able/min_buy_qty/trade_unit/stktype/scale/short_name
_ADMIN_EDITABLE_FIELDS = (
    'stock_name', 'sector',
    'is_t0_able', 'min_buy_qty', 'trade_unit',
    'stktype', 'scale',
    'short_name',
)


def update_by_admin(
    db=None,
    stock_code: str = "",
    data: Optional[Dict] = None,
) -> Optional[Row]:
    """admin 显式编辑 stocks 表(REQ-STOCK-003 + REQ-STOCK-007)

    与 upsert 的区别:
    - upsert 是爬虫自动入仓,7 天阈值跳过
    - update_by_admin 是 admin 手动改,无阈值,白名单字段全覆盖

    v46+: 若 stock_name 字段在 data 中被修改, 自动重算 short_name (REQ-STOCK-007)
          data 中若含 short_name 也会被忽略 (admin 无权改)
    """
    data = data or {}
    existing = Stocks.query_one(stock_code=stock_code)
    if existing is None:
        return None

    # v46+: 检测 stock_name 变化, 若变则重算 short_name
    new_short_name = None
    if 'stock_name' in data:
        new_short_name = to_short_name(data['stock_name'])

    update_data = {}
    for k, v in data.items():
        # v46+: 忽略 admin 传入的 short_name 字段
        if k == 'short_name':
            continue
        if k in _ADMIN_EDITABLE_FIELDS and hasattr(existing, k):
            update_data[k] = v

    # v46+: 应用重算后的 short_name
    if new_short_name is not None:
        update_data['short_name'] = new_short_name

    if not update_data:
        return existing
    return Stocks.update_one(update_data, stock_code=stock_code)


def create_by_admin(
    db=None,
    data: Optional[Dict] = None,
) -> Optional[Row]:
    """admin 手动添加 stocks 行(REQ-STOCK-006 + REQ-STOCK-007)

    与 upsert 的区别:
    - upsert 是爬虫自动入仓,7 天阈值跳过
    - create_by_admin 是 admin 手动新增,无阈值,stock_code 必填且必须不存在

    v46+: short_name 由 stock_name 自动派生 (REQ-STOCK-007)
          data 中若含 short_name 会被忽略 (admin 无权传)
    """
    data = data or {}
    stock_code = data.get('stock_code')
    if not stock_code:
        return None  # API 层会在 Pydantic 阶段拦截(必填字段)

    # 重复检查(API 层会基于 None 返 409)
    existing = Stocks.query_one(stock_code=stock_code)
    if existing is not None:
        return None

    # 只允许白名单字段,stock_code 单独处理;v46+ 排除 short_name (自动生成)
    payload = {k: v for k, v in data.items()
               if k in _ADMIN_EDITABLE_FIELDS and k in Stocks.__fields__ and k != 'short_name'}
    # v46+: 自动生成 short_name (来自 stock_name)
    payload['short_name'] = to_short_name(data.get('stock_name', ''))

    Stocks.add_one({'stock_code': stock_code, **payload})
    return Stocks.query_one(stock_code=stock_code)


def list_all(db=None, limit: Optional[int] = None) -> List[Row]:
    """按主键升序返回全表; limit 在 Python 侧切片."""
    rows = Stocks.query_all()
    return rows[:limit] if limit else rows


def list_codes(db=None) -> List[str]:
    """仅返回 stock_code 列表,用于同步任务遍历"""
    return [row.stock_code for row in Stocks.query_all()]


def to_dict(stock: Row) -> Dict:
    """Row -> dict(API 响应用, v23 字段精简, v25 加 short_name, v80 加 scale + stktype)"""
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
    """raw dict (来自 crawler) -> 标准 dict (v23 字段精简, v25 加 short_name, v80 加 scale + stktype)"""
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
