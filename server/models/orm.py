"""
SQLAlchemy ORM models for EvTrade v5 (schema refactor).

📖 **详细 schema 文档（single source of truth）**：
  参见 `openspec/specs/data-model/spec.md` — 11 张表完整结构知识库
  （字段、类型、PK、约束、业务规则、跨表引用、修改工作流）
  本文件改动前必先改 spec; spec 改动后必同步本文件。

设计原则（2026-06-15 重构）：
- 表名 / 列名：snake_case
- 日期字段：trd_date（8 位数字字符串如 '20260614'）
- 单行表（assets 等）：无主键，按约定 .first() 访问
- 含 trd_date 的表：trd_date 必入主键（复合主键）

11 张表（详见 data-model/spec.md）：
  §1 业务：orders, trades, positions, assets
  §2 配置：sys_status, trading_session, fee_config, reconcile_config
  §3 历史：reconcile_report
  §4 行情：quote_snapshots
  §5 序列：order_no_seq
"""
from datetime import datetime, timezone

def _utcnow():
    """UTC now, compatible with Python 3.6+."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
from sqlalchemy import (
    Column, Integer, String, Float, Text, DateTime, Boolean,
    CheckConstraint, Index, UniqueConstraint, Time,
)
from server.db import Base


# ─────────────── 业务表 ───────────────

class Order(Base):
    """委托主表（复合主键 trd_date + order_no）

    📖 详见 `openspec/specs/data-model/spec.md` §1
    v6 schema 改动:
    - PK (trd_date, order_id) → (trd_date, order_no)
    - order_id 出 PK,变可空,由 ord_cfm 推送写入
    - order_no 进 PK(原本就 UNIQUE,加 PK 不冲突)
    - 删 uq_orders_order_no (被 PK 替代)
    - 加 uq_orders_broker_id(order_id, trd_date):broker 真实 order_id + 交易日 唯一
    - 加 ix_orders_order_id:trd_cfm 退路查找(理论上只走 remark,这是兜底)
    - status 字段保留,语义改为 "本地推断的委托状态"（见 _infer_order_status）
    v7 schema 改动:
    - 删 client_order_id 字段 + uq_orders_client_trd 约束（幂等不再走 DB UNIQUE）
    - 删 uq_orders_broker_id 约束（order_id 下单时为空，UNIQUE 不可靠）
    - 加 user_def 字段（String(255)，外部自定义信息透传，无约束）
    - ix_orders_order_id 保留为普通 INDEX（非 UNIQUE），trd_cfm 兜底查找
    v9 schema 改动:
    - 加 order_flag 字段（Integer，0=normal 1=cancel-order，NOT NULL DEFAULT 0）
      标识本地代理的「撤单委托」行（user_def="CANCEL:{orig_order_no}"）
      broker ord_cfm 用 remark 匹配原 order_no,不会更新本行
    v10 schema 改动:
    - order_time 字段类型 String(8) → String(23)，
      格式由 "HH:MM:SS" 改为 "YYYY-MM-DD HH:MM:SS.fff" (rpc-field-alignment-ts-unify)
    """
    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_trd_status", "trd_date", "status"),
        Index("ix_orders_order_id", "order_id"),
        Index("ix_orders_stock", "stock_code"),
    )

    trd_date = Column(String(8), primary_key=True, nullable=False)  # 交易日
    order_no = Column(String(8), primary_key=True, nullable=False)  # 本地 8 位序号 (PK)
    order_id = Column(String(64), nullable=True)                    # 柜台号 (ord_cfm 到达时填入)
    user_def = Column(String(255), nullable=False, default="")      # 外部自定义信息透传
    stock_code = Column(String(16), nullable=False)
    order_type = Column(String(2), nullable=False)                  # 23=买 24=卖
    price_type = Column(Integer, nullable=False, default=11)
    price = Column(Float, nullable=False, default=0.0)
    volume = Column(Integer, nullable=False, default=0)
    traded_volume = Column(Integer, nullable=False, default=0)
    traded_amount = Column(Float, nullable=False, default=0.0)
    avg_price = Column(Float, nullable=False, default=0.0)
    cancelled_volume = Column(Integer, nullable=False, default=0)  # 累计撤单量（broker ord_cfm 累加）
    order_flag = Column(Integer, nullable=False, default=0)  # 0=normal 1=cancel-order (v9:本地代理撤单委托行)
    status = Column(String(2), nullable=False, default="48")  # 48=待报 49=已报 50=部成 51=已成 52=部撤 53=已撤 55=废单
    status_msg = Column(String(255), nullable=False, default="")
    order_time = Column(String(23), nullable=False, default="")  # v10: "YYYY-MM-DD HH:MM:SS.fff"
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=_utcnow, onupdate=_utcnow
    )
    pushed_at = Column(DateTime, nullable=True)


class Trade(Base):
    """成交表（复合主键 trd_date + order_no + trade_id）

    📖 详见 `openspec/specs/data-model/spec.md` §1（Trade 行）
    v7 schema 改动:
    - 删 order_id 字段（broker 真实号在 trd_cfm 到达时可能尚未到达）
    - 加 order_no 字段并入 PK（PK = (trd_date, order_no, trade_id)）
    - ix_trades_order(order_id) → ix_trades_order_no(order_no)（重命名）
    v9 schema 改动:
    - 加 trade_type 字段（Integer，0=normal 1=cancel-fill，NOT NULL DEFAULT 0）
      标识本地代理的「撤单成交」行（order_no 指向 cancel-order 行的 order_no）
      broker 协议撤单不推 trd_cfm,本地由 DELETE 端点同步插入
    v10 schema 改动:
    - trade_time 字段类型 String(8) → String(23)，
      格式由 "HH:MM:SS" 改为 "YYYY-MM-DD HH:MM:SS.fff" (rpc-field-alignment-ts-unify)
    """
    __tablename__ = "trades"
    __table_args__ = (
        Index("ix_trades_order_no", "order_no"),
        Index("ix_trades_trd_stock", "trd_date", "stock_code"),
    )

    trd_date = Column(String(8), primary_key=True, nullable=False)
    order_no = Column(String(8), primary_key=True, nullable=False)   # 关联本地委托号 (PK)
    trade_id = Column(String(64), primary_key=True, nullable=False)
    stock_code = Column(String(16), nullable=False)
    order_type = Column(String(2), nullable=False)
    price = Column(Float, nullable=False, default=0.0)
    volume = Column(Integer, nullable=False, default=0)
    amount = Column(Float, nullable=False, default=0.0)
    trade_time = Column(String(23), nullable=False, default="")  # v10: "YYYY-MM-DD HH:MM:SS.fff"
    trade_type = Column(Integer, nullable=False, default=0)  # 0=normal 1=cancel-fill (v9:本地代理撤单成交行)
    created_at = Column(DateTime, nullable=False, default=_utcnow)


class Position(Base):
    """持仓表（单股唯一，无 trd_date；当前快照语义）

    📖 详见 `openspec/specs/data-model/spec.md` §1（Position 行）
    📌 vol 字段：pos_cfm 推送时,row.volume 缺字段或为 0 兜底为 avl_vol
       （参见 change `2026-06-16-fix-position-vol-display`）
    """
    __tablename__ = "positions"

    stock_code = Column(String(16), primary_key=True, nullable=False)
    stock_name = Column(String(64), nullable=False, default="")
    last_vol = Column(Integer, nullable=False, default=0)   # 期初持仓
    today_buy = Column(Integer, nullable=False, default=0)
    today_sell = Column(Integer, nullable=False, default=0)
    avl_vol = Column(Integer, nullable=False, default=0)   # 可用
    vol = Column(Integer, nullable=False, default=0)       # 总持仓
    cost_price = Column(Float, nullable=False, default=0.0)
    synced_at = Column(DateTime, nullable=False, default=_utcnow)
    synced_from = Column(String(16), nullable=False, default="")  # rpc_full / push_partial / manual


class Asset(Base):
    """资金表（单行，SQLAlchemy ORM 强制需要主键，用 id=1 + CheckConstraint 限定单行）

    📖 详见 `openspec/specs/data-model/spec.md` §1（Asset 行）
    v5 schema: 移除 TRD_DATE（不再有交易日维度），保留 cash / frozen_cash / market_value / total_asset。
    业务访问方式：db.query(Asset).first() / db.query(Asset).delete() + db.add(new)
    """
    __tablename__ = "assets"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_asset_single_row"),
    )

    id = Column(Integer, primary_key=True, default=1)
    cash = Column(Float, nullable=False, default=0.0)         # 可用
    frozen_cash = Column(Float, nullable=False, default=0.0)   # 冻结
    market_value = Column(Float, nullable=False, default=0.0)
    total_asset = Column(Float, nullable=False, default=0.0)
    synced_at = Column(DateTime, nullable=False, default=_utcnow)
    synced_from = Column(String(16), nullable=False, default="")  # rpc_full / push_partial / manual


# ─────────────── 配置表 ───────────────

class SysStatus(Base):
    """系统级状态机（含交易日；主键 trd_date）

    📖 详见 `openspec/specs/data-model/spec.md` §2（SysStatus 行）
    """
    __tablename__ = "sys_status"
    __table_args__ = (
        Index("ix_sys_status_status", "status"),
    )

    trd_date = Column(String(8), primary_key=True, nullable=False)   # YYYYMMDD
    status = Column(String(16), nullable=False, default="pending")   # pending / active / closed
    is_half_day = Column(Integer, nullable=False, default=0)
    initialized_at = Column(DateTime, nullable=True)
    initialized_by = Column(Integer, nullable=True)                  # FK users.id
    closed_at = Column(DateTime, nullable=True)
    closed_by = Column(Integer, nullable=True)
    remark = Column(String(255), nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=_utcnow)


class TradingSession(Base):
    """交易时段配置（单行）

    📖 详见 `openspec/specs/data-model/spec.md` §2（TradingSession 行）
    """
    __tablename__ = "trading_session"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_session_single_row"),
    )

    id = Column(Integer, primary_key=True, default=1)
    morning_start = Column(Time, nullable=False)        # 09:15
    morning_end = Column(Time, nullable=False)          # 11:30
    afternoon_start = Column(Time, nullable=False)      # 13:00
    afternoon_end = Column(Time, nullable=False)        # 15:00
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)


class FeeConfig(Base):
    """费率配置（单行）

    📖 详见 `openspec/specs/data-model/spec.md` §2（FeeConfig 行）
    """
    __tablename__ = "fee_config"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_fee_single_row"),
    )

    id = Column(Integer, primary_key=True, default=1)
    commission_rate = Column(Float, nullable=False, default=0.0001)   # 万一
    stamp_tax_rate = Column(Float, nullable=False, default=0.001)     # 千 1
    slippage = Column(Float, nullable=False, default=0.001)            # 0.1%
    min_commission = Column(Float, nullable=False, default=5.0)         # 最低 5 元
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)
    updated_by = Column(Integer, nullable=True)


class ReconcileConfig(Base):
    """对账配置（单行）

    📖 详见 `openspec/specs/data-model/spec.md` §2（ReconcileConfig 行）
    """
    __tablename__ = "reconcile_config"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_reconcile_cfg_single_row"),
    )

    id = Column(Integer, primary_key=True, default=1)
    auto_reconcile = Column(Integer, nullable=False, default=0)        # 0=人工 1=自动
    auto_use_broker_data = Column(Integer, nullable=False, default=1)  # 自动时 1=以柜台为准 0=以本地为准
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)
    updated_by = Column(Integer, nullable=True)


# ─────────────── 历史 ───────────────

class ReconcileReport(Base):
    """对账历史报告（复合主键 trd_date + mode + created_at）

    📖 详见 `openspec/specs/data-model/spec.md` §3
    """
    __tablename__ = "reconcile_report"
    __table_args__ = (
        Index("ix_reconcile_report_trd", "trd_date"),
    )

    trd_date = Column(String(8), primary_key=True, nullable=False)
    mode = Column(String(16), primary_key=True, nullable=False)        # auto / manual
    created_at = Column(DateTime, primary_key=True, nullable=False, default=_utcnow)
    diffs_json = Column(Text, nullable=False, default="[]")
    broker_asset_json = Column(Text, nullable=False, default="")
    local_asset_json = Column(Text, nullable=False, default="")
    broker_positions_json = Column(Text, nullable=False, default="")
    local_positions_json = Column(Text, nullable=False, default="")
    rpc_status = Column(String(16), nullable=False, default="ok")  # ok / partial / failed
    error_message = Column(String(512), nullable=False, default="")
    created_by = Column(Integer, nullable=True)


# ─────────────── 行情 ───────────────

class QuoteSnapshot(Base):
    """行情快照

    📖 详见 `openspec/specs/data-model/spec.md` §4
    """
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
    ts = Column(DateTime, nullable=False, default=_utcnow, index=True)


# ─────────────── 序列 ───────────────

class OrderNoSeq(Base):
    """订单序号生成器（单行）

    📖 详见 `openspec/specs/data-model/spec.md` §5
    """
    __tablename__ = "order_no_seq"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_order_no_seq_single_row"),
    )

    id = Column(Integer, primary_key=True, default=1)
    last_value = Column(Integer, nullable=False, default=10000000)  # 8 位起
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)
