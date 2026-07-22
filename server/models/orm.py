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

change v_next-sys-status-single-row (2026-07-22):
  - sys_status 改为单行宽表 (id=1 PK, 强制 CHECK id=1)
  - trd_date 不再是 PK; 切日 = UPDATE id=1 行的 trd_date
  - 历史交易日仍由 reconcile_report.trd_date 记录
  - Asset 也确认无 PK (单行表)
"""
from sqlalchemy import (
    Column, Integer, String, Float, Text, DateTime, CheckConstraint, Index, Time,
    Boolean,
    UniqueConstraint,
)
from sqlalchemy.orm import Session
from typing import Optional

from server.db import Base
from server.utils.time import _utcnow


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
    v13 NEW schema 改动（layered-architecture-and-strategy-master）:
    - 加 raw_id 字段（String(8)，nullable=True）
      cancel-row 写入时存 = 原 order_no；普通 strategy 委托 raw_id 永远为 NULL
      与 user_def="CANCEL:{orig.order_no}" 共存（结构化冗余，便于 JOIN 过滤）
      不加 NOT NULL DEFAULT — 旧 orders 数据无破坏（NULL fallback）
    v18 NEW schema 改动（t0-task-management）:
    - 加 task_id 字段（Integer，nullable=True）
      关联 t0_tasks.id (REQ-TRADE-013)；NULL 表示无显式 task 关联
      与 user_def='T0' 共存：有 task 的单同时写 user_def='T0' AND task_id=<id>；
      无 task 的旧 T0 单保持 user_def='T0' AND task_id=NULL（向后兼容 REQ-TRADE-006）
      加 ix_orders_task_id 索引（task 维度聚合 + balance 配平查询）
    v66 NEW schema 改动（orders-strategy-type）：
    - 加 strategy_type 字段（TINYINT，NOT NULL DEFAULT 0）
      REQ-TRADE-026 业务契约：0=普通单（Trade.vue 下单），1=快速做T（T0Trade.vue 下单）
      历史数据不回填（user_def='T0' 单保持 strategy_type=0，向后兼容 v18 task_id 同策略）
      加 ix_orders_strategy_type 索引（缓存过滤 + 未来策略维度报表）
      DB 迁移：server/migrations/2026-07-17-add-orders-strategy-type.py
    """
    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_trd_status", "trd_date", "status"),
        Index("ix_orders_order_id", "order_id"),
        Index("ix_orders_stock", "stock_code"),
        Index("ix_orders_user_def", "user_def"),  # change strategy_trade: 支撑策略关联查询
        Index("ix_orders_task_id", "task_id"),    # change t0-task-management: REQ-TRADE-013 task 维度聚合
        Index("ix_orders_strategy_type", "strategy_type"),  # change orders-strategy-type: REQ-TRADE-026 缓存过滤 + 策略维度聚合
    )

    trd_date = Column(String(8), primary_key=True, nullable=False)  # 交易日
    order_no = Column(String(8), primary_key=True, nullable=False)  # 本地 8 位序号 (PK)
    order_id = Column(String(64), nullable=True)                    # 柜台号 (ord_cfm 到达时填入)
    user_def = Column(String(255), nullable=False, default="")      # 外部自定义信息透传
    stock_code = Column(String(16), nullable=False)
    order_type = Column(String(2), nullable=False)                  # 23=买 24=卖
    price_type = Column(Integer, nullable=False, default=0)
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
    raw_id = Column(String(8), nullable=True)  # v13 NEW: cancel-row 写 = 原 order_no；普通行 NULL
    task_id = Column(Integer, nullable=True)    # v18 NEW: 关联 t0_tasks.id；NULL = 无显式 task
    strategy_type = Column(Integer, nullable=False, default=0)  # v66 NEW: REQ-TRADE-026; 0=普通单 1=快速做T
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
    📌 vol 字段来源（change consolidate-position-data-flow 后）：
       - day-init：do_reconcile 全表覆盖（写入 avl_vol / vol / cost_price）
       - intra-day：trd_cfm push handler 按 trade_type 累加/扣减（vol / avl_vol ± volume）
       - 不再依赖 pos_cfm 推送（xtquant broker 不发）
    📌 change add-manual-adjust-and-history-pages (v12):
       - 删除 today_buy / today_sell 列（v5 schema 遗留，从未被消费）
       - manual 调平 API 直接对 vol / avl_vol 做原子加减（不存 delta 字段）
       - 当日买卖累计语义改由 Trade 表 SUM 聚合替代
    """
    __tablename__ = "positions"

    stock_code = Column(String(16), primary_key=True, nullable=False)
    stock_name = Column(String(64), nullable=False, default="")
    last_vol = Column(Integer, nullable=False, default=0)   # 期初持仓（仅 do_reconcile 写入）
    avl_vol = Column(Integer, nullable=False, default=0)   # 可用（do_reconcile 写入 + manual 调平）
    vol = Column(Integer, nullable=False, default=0)       # 总持仓（do_reconcile 写入 + trd_cfm 增量 + manual 调平）
    cost_price = Column(Float, nullable=False, default=0.0)  # 仅 do_reconcile 写入
    synced_at = Column(DateTime, nullable=False, default=_utcnow)
    # synced_from 取值:
    #   - rpc_full: do_reconcile 写入
    #   - push_partial: trd_cfm push handler 增量
    #   - manual: admin 调平 API 写入（再次 reconcile 会重置为 rpc_full）
    synced_from = Column(String(16), nullable=False, default="")


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
    """系统级状态机（单行宽表, v_next 重构:不再用 trd_date 作 PK）

    📖 详见 `openspec/specs/data-model/spec.md` §2（SysStatus 行）

    设计原则 (v_next 重构, 用户明令):
      - 表只存 1 行: 唯一的『当前交易日』状态 (trd_date + status)
      - PK = id=1 (强制 CHECK id=1); 历史交易日由 reconcile_report.trd_date 记录
      - 切日 = UPDATE 这一行的 trd_date 字段, 不是插新行
    """
    __tablename__ = "sys_status"

    id = Column(Integer, primary_key=True, nullable=False, default=1)
    trd_date = Column(String(8), nullable=False)                     # YYYYMMDD
    status = Column(String(16), nullable=False, default="closed")     # active | closed
    is_half_day = Column(Integer, nullable=False, default=0)
    initialized_at = Column(DateTime, nullable=True)
    initialized_by = Column(Integer, nullable=True)
    closed_at = Column(DateTime, nullable=True)
    closed_by = Column(Integer, nullable=True)
    remark = Column(String(255), nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)


def get_active_trd_date(db: Session) -> Optional[str]:
    """v_next 单行接口:获取当前交易日 trd_date (status='active')

    返回 None 表示未激活/刚闭市。
    """
    row = db.query(SysStatus.trd_date).filter(SysStatus.id == 1, SysStatus.status == 'active').first()
    return row[0] if row else None


def get_active_sysstatus(db: Session) -> Optional[SysStatus]:
    """v_next 单行接口:获取当前 SysStatus 完整行 (id=1)

    返回 None 表示 id=1 行不存在 (极端脏数据) — 调用方应宽容 None。
    """
    return db.query(SysStatus).filter(SysStatus.id == 1).first()


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


class SysConfig(Base):
    """统一配置表 (v78)

    📖 详见 `openspec/specs/data-model/spec.md` §3 (SysConfig 表)
    主键: (user, cfg_key) 复合主键
    - user='0' 表示全局默认配置 (任何用户未配置时回退到这里)
    - user='<username>' 表示该用户专属覆盖
    - 启动时一次性加载到内存 cache, 业务层从 cache 读
    - 写时同步更新 cache + DB
    """
    __tablename__ = "sys_config"
    __table_args__ = (
        Index("ix_sys_config_user", "user"),
    )

    user = Column(String(64), primary_key=True, nullable=False, default="0")
    cfg_key = Column(String(64), primary_key=True, nullable=False)
    cfg_val = Column(String(512), nullable=False, default="")
    desc = Column(String(255), nullable=False, default="")
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)
    updated_by = Column(String(64), nullable=True)


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

    2026-07-09 quote-snapshot-subscribe: latest-only 模型（每 stock_code 1 行）。
      - 字段名规范化: open→open_price / high→high_price / low→low_price（语义清楚）
      - volume 是 Integer（手/股数，非金额）
      - 加 stock_code UniqueConstraint + 应用层 INSERT...ON CONFLICT/UPDATE UPSERT
    """
    __tablename__ = "quote_snapshots"
    __table_args__ = (
        Index("ix_quote_stock_ts", "stock_code", "ts"),
        UniqueConstraint("stock_code", name="uq_quote_snapshots_stock_code"),
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


# ─────────────── T0 任务表 ───────────────

class Stock(Base):
    """股票基础信息表（v23 change slim-stocks-table, 2026-07-12）

    📖 详见 `openspec/specs/data-model/spec.md` §13 (stocks)

    字段精简（v21→v23）：删除 9 个未被消费的字段（industry/market/list_date/
    total_share/float_share/market_cap/pe_ratio/pb_ratio/intro），新增 3 个业务
    字段（is_t0_able/min_buy_qty/trade_unit）用于 admin 配置回转标志与买卖粒度。

    - stock_code 是 PK（与 quote_snapshots 一致,带 .SH/.SZ 后缀）
    - 6 个业务字段(基础信息 + 交易粒度)
    - 0 个字段索引(sector 暂未加索引,数据量小可走全表扫)
    - updated_at 自动 ON UPDATE,用于增量 upsert 的"7 天内跳过"逻辑
    - 历史 14 字段数据已备份至 stocks_legacy 表
    v25 schema 改动 (stocks-cache-and-short-name, 2026-07-12):
    - 加 short_name 字段 (String(16), nullable=True)
      拼音首字母简称(平安银行→PAYH),用于前端 autocomplete 首字母快速筛选
      backfill 由 server/scripts/backfill_short_name.py 一次性灌入
      用户后续"自己去维护",不再走自动同步(同步任务 v26 移除)
    """
    __tablename__ = "stocks"

    stock_code = Column(String(16), primary_key=True, nullable=False)  # 000001.SZ
    stock_name = Column(String(64), nullable=False, default="")
    sector = Column(String(64), nullable=True)                # 板块(申万二级)
    is_t0_able = Column(Boolean, nullable=False, default=False)  # 是否支持 T+0 回转
    min_buy_qty = Column(Integer, nullable=False, default=100)  # 最小买入数量(A 股默认 100)
    trade_unit = Column(Integer, nullable=False, default=1)      # 买卖单位
    short_name = Column(String(16), nullable=True)              # v25: 拼音首字母简称(平安银行→PAYH),admin 编辑/手动维护
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)


class T0Task(Base):
    """T0 做 T 任务实体（v18 change t0-task-management）

    📖 详见 `openspec/specs/data-model/spec.md` §12
    REQ-TRADE-013: 一等公民实体，区别于 Order.user_def='T0' 的隐式标签。
    一份 task = 一只券 + 一个底仓 + 一个目标开仓量 + 一个生命周期。

    字段语义:
    - base_volume: 底仓量（"保留部分底仓"语义）；配平目标 = base_volume + target_volume
    - target_volume: 目标开仓量（区别于现仓位的净增量；可为负数表示净减仓目标）
    - coefficient: 配平系数（沿用 REQ-TRADE-005 语义）
    - status: 生命周期 active / closed / archived
    - created_trd_date: 业务字段（创建时所属交易日），不用 created_at 倒推
    """
    __tablename__ = "t0_tasks"
    __table_args__ = (
        Index("ix_t0_tasks_stock_code", "stock_code"),
        Index("ix_t0_tasks_status_created", "status", "created_at"),
        Index("ix_t0_tasks_user_status", "user_id", "status"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False)                # owner; 与 users 表不强制 FK
    stock_code = Column(String(16), nullable=False)          # 带 .SH/.SZ 后缀
    base_volume = Column(Integer, nullable=False, default=0)
    target_volume = Column(Integer, nullable=False, default=0)
    coefficient = Column(Float, nullable=False, default=1.0)
    status = Column(String(16), nullable=False, default="active")  # active / closed / archived
    note = Column(String(255), nullable=True)
    created_trd_date = Column(String(8), nullable=False)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)  # v18: status 流转时自动更新
    closed_at = Column(DateTime, nullable=True)
