"""
test_orm.py — ORM 模型结构回归

覆盖：
- change add-manual-adjust-and-history-pages (v12):
  - Position 表已删除 today_buy / today_sell 两列（v5 schema 遗留死字段）
- v5 schema invariants:
  - Order / Trade / Position / Asset 主键与必填字段类型稳定

不依赖 DB（仅 inspect Column 列表），无需 init_db，速度快。
"""
import pytest
from sqlalchemy import Integer, Float, String, DateTime

from server.models.orm import Position, Asset, Order, Trade


def _column_names(model):
    return {c.key for c in model.__table__.columns}


def _column(model, key):
    for c in model.__table__.columns:
        if c.key == key:
            return c
    return None


# ─── Position 字段表（v12 删 today_buy/today_sell 后） ───

def test_position_table_no_today_buy():
    """v12: today_buy 列已从 Position 表删除

    是 v5 schema 遗留死字段：do_reconcile 写入后无人读、push handler 不增量、前端从未消费。
    当日买卖累计语义改由 Trade 表 SUM 聚合替代。
    """
    cols = _column_names(Position)
    assert "today_buy" not in cols, "Position.today_buy 列已被 v12 删除"


def test_position_table_no_today_sell():
    """v12: today_sell 列已从 Position 表删除（同上）"""
    cols = _column_names(Position)
    assert "today_sell" not in cols, "Position.today_sell 列已被 v12 删除"


def test_position_table_core_columns_present():
    """v12 Position 保留字段：PK + 业务核心 5 列 + synced_at + synced_from"""
    cols = _column_names(Position)
    expected = {
        "stock_code",   # PK
        "stock_name",
        "last_vol",     # 期初（仅 do_reconcile 写）
        "avl_vol",      # 可用（do_reconcile + manual）
        "vol",          # 总持仓（do_reconcile + trd_cfm + manual）
        "cost_price",
        "synced_at",
        "synced_from",
    }
    assert expected.issubset(cols), f"Position 缺少核心字段: {expected - cols}"


def test_position_vol_field_int_not_null():
    """Position.vol 必须是 Integer 非空"""
    col = _column(Position, "vol")
    assert col is not None
    assert isinstance(col.type, Integer)
    assert col.nullable is False
    assert col.default.arg == 0


def test_position_synced_from_accepts_manual():
    """v12: Position.synced_from 取值新增 'manual' (admin 调平 API 写入)

    业务约束在 service 层；ORM 层只保证字符串字段存得下。
    """
    col = _column(Position, "synced_from")
    assert col is not None
    assert isinstance(col.type, String)
    # length=16 足够装 'rpc_full' / 'push_partial' / 'manual'
    assert col.type.length >= len("push_partial"), "synced_from 长度太短"


# ─── Asset v12 新增 'manual' 标记 ───

def test_asset_synced_from_field_present():
    """Asset.synced_from 字段存在"""
    col = _column(Asset, "synced_from")
    assert col is not None
    assert isinstance(col.type, String)


def test_asset_single_row_constraint():
    """Asset 单行约束：id=1 + CheckConstraint

    单行表设计：业务 db.query(Asset).first() 访问，不存历史快照。
    """
    from sqlalchemy import CheckConstraint
    check_constraints = [
        c for c in Asset.__table__.constraints if isinstance(c, CheckConstraint)
    ]
    assert any("id = 1" in str(c.sqltext) for c in check_constraints), \
        "Asset 必须保留 'id = 1' 单行约束"


# ─── Order / Trade v7/v10 invariants（防止回归） ───

def test_order_pk_is_trd_date_and_order_no():
    """v6+ Order PK = (trd_date, order_no)，order_id 出 PK"""
    pk_cols = [c.key for c in Order.__table__.primary_key.columns]
    assert pk_cols == ["trd_date", "order_no"], f"Order PK 变更: {pk_cols}"


def test_trade_pk_is_trd_date_order_no_trade_id():
    """v7 Trade PK = (trd_date, order_no, trade_id)"""
    pk_cols = [c.key for c in Trade.__table__.primary_key.columns]
    assert pk_cols == ["trd_date", "order_no", "trade_id"], f"Trade PK 变更: {pk_cols}"


def test_trade_no_order_id_column():
    """v7 Trade 删除 order_id 字段（trd_cfm 到达时 broker order_id 可能未到）"""
    cols = _column_names(Trade)
    assert "order_id" not in cols, "Trade.order_id 已被 v7 删除"


def test_order_time_string_23():
    """v10 order_time 类型 String(23), 格式 'YYYY-MM-DD HH:MM:SS.fff'"""
    col = _column(Order, "order_time")
    assert col is not None
    assert isinstance(col.type, String)
    assert col.type.length == 23, f"order_time 长度变更: {col.type.length}"
