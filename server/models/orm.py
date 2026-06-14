"""
SQLAlchemy ORM models for EvTrade v4.

命名规范：
- 表名/列名：snake_case
- 交易日期字段：TRD_DATE（8 位数字字符串如 '20260614'，列名沿用用户约定）
- 单行表：id=1，CHECK (id=1) 约束

10 张表：
  业务：orders, trades, positions, assets
  配置：trading_day, trading_session, fee_config, reconcile_config
  历史：reconcile_report
  行情：quote_snapshots
  序列：order_no_seq
"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Text, DateTime, Boolean,
    CheckConstraint, Index, UniqueConstraint, Time,
)
from db import Base


# ─────────────── 业务表 ───────────────

class Order(Base):
    """委托主表"""
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("order_id", name="uq_orders_order_id"),
        UniqueConstraint("client_order_id", name="uq_orders_client_order_id"),
        UniqueConstraint("order_no", name="uq_orders_order_no"),
        Index("ix_orders_trd_status", "TRD_DATE", "status"),
        Index("ix_orders_stock", "stock_code"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String(64), nullable=False)            # 柜台号
    client_order_id = Column(String(64), nullable=False)     # 客户端幂等号
    order_no = Column(String(8), nullable=False)             # 本地 8 位序号
    order_remark = Column(String(64), nullable=False, default="")
    TRD_DATE = Column(String(8), nullable=False)            # 交易日
    stock_code = Column(String(16), nullable=False)
    order_type = Column(String(2), nullable=False)           # 23=买 24=卖
    price_type = Column(Integer, nullable=False, default=11)
    price = Column(Float, nullable=False, default=0.0)
    volume = Column(Integer, nullable=False, default=0)
    traded_volume = Column(Integer, nullable=False, default=0)
    traded_amount = Column(Float, nullable=False, default=0.0)
    avg_price = Column(Float, nullable=False, default=0.0)
    status = Column(String(2), nullable=False, default="48")  # 48=待报 49=已报 50=部成 51=已成 52=部撤 53=已撤 55=废单
    status_msg = Column(String(255), nullable=False, default="")
    order_time = Column(String(8), nullable=False, default="")  # HH:MM:SS
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    pushed_at = Column(DateTime, nullable=True)


class Trade(Base):
    """成交表"""
    __tablename__ = "trades"
    __table_args__ = (
        UniqueConstraint("trade_id", name="uq_trades_trade_id"),
        Index("ix_trades_order", "order_id"),
        Index("ix_trades_trd_stock", "TRD_DATE", "stock_code"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_id = Column(String(64), nullable=False)
    order_id = Column(String(64), nullable=False)
    TRD_DATE = Column(String(8), nullable=False)
    stock_code = Column(String(16), nullable=False)
    order_type = Column(String(2), nullable=False)
    price = Column(Float, nullable=False, default=0.0)
    volume = Column(Integer, nullable=False, default=0)
    amount = Column(Float, nullable=False, default=0.0)
    trade_time = Column(String(8), nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class Position(Base):
    """持仓表"""
    __tablename__ = "positions"
    __table_args__ = (
        UniqueConstraint("TRD_DATE", "stock_code", name="uq_positions_trd_stock"),
        Index("ix_positions_stock", "stock_code"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    TRD_DATE = Column(String(8), nullable=False)
    stock_code = Column(String(16), nullable=False)
    stock_name = Column(String(64), nullable=False, default="")
    initial_position = Column(Integer, nullable=False, default=0)  # 日初
    today_buy = Column(Integer, nullable=False, default=0)
    today_sell = Column(Integer, nullable=False, default=0)
    available = Column(Integer, nullable=False, default=0)
    total = Column(Integer, nullable=False, default=0)
    cost = Column(Float, nullable=False, default=0.0)
    synced_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    synced_from = Column(String(16), nullable=False, default="")  # rpc_full / push_partial / manual


class Asset(Base):
    """资金表（单行）"""
    __tablename__ = "assets"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_assets_single_row"),
        UniqueConstraint("TRD_DATE", name="uq_assets_trd"),
    )

    id = Column(Integer, primary_key=True, default=1)
    TRD_DATE = Column(String(8), nullable=False)
    cash = Column(Float, nullable=False, default=0.0)         # 可用
    frozen_cash = Column(Float, nullable=False, default=0.0)   # 冻结
    market_value = Column(Float, nullable=False, default=0.0)
    total_asset = Column(Float, nullable=False, default=0.0)
    synced_at = Column(DateTime, nullable=False, default=datetime.utcnow)


# ─────────────── 配置表 ───────────────

class TradingDay(Base):
    """交易日状态机"""
    __tablename__ = "trading_day"
    __table_args__ = (
        Index("ix_trading_day_status", "status"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    current_date = Column(String(8), nullable=False)   # YYYYMMDD
    status = Column(String(16), nullable=False, default="pending")  # pending / active / closed
    is_half_day = Column(Integer, nullable=False, default=0)
    initialized_at = Column(DateTime, nullable=True)
    initialized_by = Column(Integer, nullable=True)     # FK users.id
    closed_at = Column(DateTime, nullable=True)
    closed_by = Column(Integer, nullable=True)
    remark = Column(String(255), nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class TradingSession(Base):
    """交易时段配置（单行）"""
    __tablename__ = "trading_session"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_session_single_row"),
    )

    id = Column(Integer, primary_key=True, default=1)
    morning_start = Column(Time, nullable=False)        # 09:15
    morning_end = Column(Time, nullable=False)          # 11:30
    afternoon_start = Column(Time, nullable=False)      # 13:00
    afternoon_end = Column(Time, nullable=False)        # 15:00
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class FeeConfig(Base):
    """费率配置（单行）"""
    __tablename__ = "fee_config"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_fee_single_row"),
    )

    id = Column(Integer, primary_key=True, default=1)
    commission_rate = Column(Float, nullable=False, default=0.0001)   # 万一
    stamp_tax_rate = Column(Float, nullable=False, default=0.001)     # 千 1
    slippage = Column(Float, nullable=False, default=0.001)            # 0.1%
    min_commission = Column(Float, nullable=False, default=5.0)         # 最低 5 元
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = Column(Integer, nullable=True)


class ReconcileConfig(Base):
    """对账配置（单行）"""
    __tablename__ = "reconcile_config"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_reconcile_cfg_single_row"),
    )

    id = Column(Integer, primary_key=True, default=1)
    auto_reconcile = Column(Integer, nullable=False, default=0)        # 0=人工 1=自动
    auto_use_broker_data = Column(Integer, nullable=False, default=1)  # 自动时 1=以柜台为准 0=以本地为准
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = Column(Integer, nullable=True)


# ─────────────── 历史 ───────────────

class ReconcileReport(Base):
    """对账历史报告"""
    __tablename__ = "reconcile_report"

    id = Column(Integer, primary_key=True, autoincrement=True)
    TRD_DATE = Column(String(8), nullable=False)
    mode = Column(String(16), nullable=False)              # auto / manual
    diffs_json = Column(Text, nullable=False, default="[]")
    broker_asset_json = Column(Text, nullable=False, default="")
    local_asset_json = Column(Text, nullable=False, default="")
    broker_positions_json = Column(Text, nullable=False, default="")
    local_positions_json = Column(Text, nullable=False, default="")
    rpc_status = Column(String(16), nullable=False, default="ok")  # ok / partial / failed
    error_message = Column(String(512), nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_by = Column(Integer, nullable=True)


# ─────────────── 行情 ───────────────

class QuoteSnapshot(Base):
    """行情快照"""
    __tablename__ = "quote_snapshots"
    __table_args__ = (
        Index("ix_quote_stock_ts", "stock_code", "ts"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    stock_code = Column(String(16), nullable=False)
    last_price = Column(Float, nullable=False, default=0.0)
    open_price = Column(Float, nullable=False, default=0.0)
    high_price = Column(Float, nullable=False, default=0.0)
    low_price = Column(Float, nullable=False, default=0.0)
    prev_close = Column(Float, nullable=False, default=0.0)
    volume = Column(Integer, nullable=False, default=0)
    amount = Column(Float, nullable=False, default=0.0)
    bid1_price = Column(Float, nullable=False, default=0.0)
    bid1_vol = Column(Integer, nullable=False, default=0)
    bid2_price = Column(Float, nullable=False, default=0.0)
    bid2_vol = Column(Integer, nullable=False, default=0)
    bid3_price = Column(Float, nullable=False, default=0.0)
    bid3_vol = Column(Integer, nullable=False, default=0)
    bid4_price = Column(Float, nullable=False, default=0.0)
    bid4_vol = Column(Integer, nullable=False, default=0)
    bid5_price = Column(Float, nullable=False, default=0.0)
    bid5_vol = Column(Integer, nullable=False, default=0)
    ask1_price = Column(Float, nullable=False, default=0.0)
    ask1_vol = Column(Integer, nullable=False, default=0)
    ask2_price = Column(Float, nullable=False, default=0.0)
    ask2_vol = Column(Integer, nullable=False, default=0)
    ask3_price = Column(Float, nullable=False, default=0.0)
    ask3_vol = Column(Integer, nullable=False, default=0)
    ask4_price = Column(Float, nullable=False, default=0.0)
    ask4_vol = Column(Integer, nullable=False, default=0)
    ask5_price = Column(Float, nullable=False, default=0.0)
    ask5_vol = Column(Integer, nullable=False, default=0)
    ts = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)


# ─────────────── 序列 ───────────────

class OrderNoSeq(Base):
    """订单序号生成器（单行）"""
    __tablename__ = "order_no_seq"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_order_no_seq_single_row"),
    )

    id = Column(Integer, primary_key=True, default=1)
    last_value = Column(Integer, nullable=False, default=10000000)  # 8 位起
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
