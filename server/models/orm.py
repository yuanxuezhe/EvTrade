"""
SQLAlchemy ORM models for EvTrade.

📖 **详细 schema 文档（single source of truth）**：
  参见 `openspec/specs/data-model/spec.md` — 11 张表完整结构知识库
  （字段、类型、PK、约束、业务规则、跨表引用、修改工作流）
  本文件改动前必先改 spec; spec 改动后必同步本文件。

设计原则：
- 表名 / 列名：snake_case
- 日期字段：trd_date（8 位数字字符串如 '20260614'）
- 单行表（assets 等）：无主键，按约定 .first() 访问
- 含 trd_date 的表：trd_date 必入主键（复合主键）

11 张表（详见 data-model/spec.md）：
  §1 业务：orders, trades, positions, assets
  §2 配置：sys_status (单行), sys_config (统一配置, user-keyed)
  §3 历史：reconcile_report
  §4 行情：quote_snapshots
  §5 序列：order_no_seq

change v_next-sys-status-single-row:
  - sys_status 改为单行宽表 (id=1 PK, 强制 CHECK id=1)
  - trd_date 不再是 PK; 切日 = UPDATE id=1 行的 trd_date
  - 历史交易日仍由 reconcile_report.trd_date 记录
  - Asset 也确认无 PK (单行表)
"""
from sqlalchemy import (
    Column, Integer, String, Float, Text, DateTime, CheckConstraint, Index, Time,
    Boolean, SmallInteger,
    UniqueConstraint,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Session
from typing import Optional

from server.db import Base
from server.utils.time import _utcnow


# ─────────────── 业务表 ───────────────

class Order(Base):
    """委托主表（复合主键 trd_date + order_no）

    📖 详见 `openspec/specs/data-model/spec.md` §1

    字段要点:
    - PK (trd_date, order_no); order_id 可空,由 ord_cfm 推送写入
    - uq_orders_order_no 已由 PK 替代; ix_orders_order_id 为普通 INDEX (非 UNIQUE),trd_cfm 兜底查找
    - user_def (String(255)): 外部自定义信息透传,无约束;幂等不走 DB UNIQUE
    - order_flag: 0=normal 1=cancel-order,标识本地代理「撤单委托」行
      (user_def="CANCEL:{orig_order_no}";broker ord_cfm 用 remark 匹配原 order_no,不更新本行)
    - order_time 格式 "YYYY-MM-DD HH:MM:SS.fff"
    - raw_id (String(8), nullable): cancel-row 写入时存 = 原 order_no;普通委托永远 NULL
      (与 user_def="CANCEL:{orig.order_no}" 共存,结构化冗余,便于 JOIN 过滤)
    - task_id (Integer, nullable): 关联 t0_tasks.id (REQ-TRADE-013);NULL = 无显式 task
      (有 task 的单同时写 user_def='T0' AND task_id=<id>;旧 T0 单 user_def='T0' AND task_id=NULL,向后兼容 REQ-TRADE-006)
    - strategy_type: REQ-TRADE-026;0=普通单(Trade.vue 下单) 1=快速做T(T0Trade.vue 下单) 2=策略下单(task_id=strategy_order.task_id)
      (user_def='T0' 历史单保持 strategy_type=0,不回填)
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
    order_flag = Column(Integer, nullable=False, default=0)  # 0=normal 1=cancel-order (本地代理撤单委托行)
    status = Column(String(2), nullable=False, default="48")  # 48=待报 49=已报 50=部成 51=已成 52=部撤 53=已撤 55=废单
    status_msg = Column(String(255), nullable=False, default="")
    order_time = Column(String(23), nullable=False, default="")  # "YYYY-MM-DD HH:MM:SS.fff"
    raw_id = Column(String(8), nullable=True)  # cancel-row 写 = 原 order_no；普通行 NULL
    task_id = Column(Integer, nullable=True)    # 关联 t0_tasks.id；NULL = 无显式 task
    strategy_type = Column(Integer, nullable=False, default=0)  # REQ-TRADE-026; 0=普通单 1=快速做T 2=策略下单 (task_id=strategy_order.task_id)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=_utcnow, onupdate=_utcnow
    )
    pushed_at = Column(DateTime, nullable=True)


class Trade(Base):
    """成交表（复合主键 trd_date + order_no + trade_id）

    📖 详见 `openspec/specs/data-model/spec.md` §1（Trade 行）

    字段要点:
    - PK = (trd_date, order_no, trade_id);order_id 不入库
      (broker 真实号在 trd_cfm 到达时可能尚未到达);ix_trades_order_no(order_no) 普通索引
    - trade_type: 0=normal 1=cancel-fill,标识本地代理「撤单成交」行
      (order_no 指向 cancel-order 行的 order_no;broker 协议撤单不推 trd_cfm,本地由 DELETE 端点同步插入)
    - trade_time 格式 "YYYY-MM-DD HH:MM:SS.fff"
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
    trade_time = Column(String(23), nullable=False, default="")  # "YYYY-MM-DD HH:MM:SS.fff"
    trade_type = Column(Integer, nullable=False, default=0)  # 0=normal 1=cancel-fill (本地代理撤单成交行)
    created_at = Column(DateTime, nullable=False, default=_utcnow)


class Position(Base):
    """持仓表（单股唯一，无 trd_date；当前快照语义）

    📖 详见 `openspec/specs/data-model/spec.md` §1（Position 行）
    📌 vol 字段来源（change consolidate-position-data-flow）：
       - day-init：do_reconcile 全表覆盖（写入 avl_vol / vol / cost_price）
       - intra-day：trd_cfm push handler 按 trade_type 累加/扣减（vol / avl_vol ± volume）
       - 不依赖 pos_cfm 推送（xtquant broker 不发）
    📌 manual 调平（change add-manual-adjust-and-history-pages）:
       - 无 today_buy / today_sell 列（从未被消费）
       - manual 调平 API 直接对 vol / avl_vol 做原子加减（不存 delta 字段）
       - 当日买卖累计语义由 Trade 表 SUM 聚合替代
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
    无 TRD_DATE（无交易日维度），保留 cash / frozen_cash / market_value / total_asset。
    业务访问方式：db.query(Asset).first() / db.query(Asset).delete() + db.add(new)
    """
    __tablename__ = "assets"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_asset_single_row"),
    )

    id = Column(Integer, primary_key=True, default=1)
    cash = Column(Float, nullable=False, default=0.0)         # 可用
    available = Column(Float, nullable=False, default=0.0)    # 可用资金 (= cash, 单独字段供前端命名直接读)
    frozen_cash = Column(Float, nullable=False, default=0.0)   # 冻结
    market_value = Column(Float, nullable=False, default=0.0)
    total_asset = Column(Float, nullable=False, default=0.0)
    # 期初总资产 (早上 do_reconcile 系统初始化时计算: 可用资金 + sum(昨收 * 持仓))
    last_asset = Column(Float, nullable=False, default=0.0)
    synced_at = Column(DateTime, nullable=False, default=_utcnow)
    synced_from = Column(String(16), nullable=False, default="")  # rpc_full / push_partial / manual


# ─────────────── 配置表 ───────────────

class SysStatus(Base):
    """系统级状态机（单行宽表, 不用 trd_date 作 PK）

    📖 详见 `openspec/specs/data-model/spec.md` §2（SysStatus 行）

    设计原则 (用户明令):
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


def get_active_trd_date(db: Optional["Session"] = None) -> Optional[str]:  # noqa: ARG001
    """获取当前交易日 trd_date (status='active')

    返回 None 表示未激活/刚闭市。

    走 server.tables.SysStatus (兼容保留 db 参数但忽略)
    """
    from server.tables import SysStatus
    row = SysStatus.query_one(id=1)
    if not row:
        return None
    if row.status == 'active':
        return row.trd_date
    return None


def get_active_sysstatus(db: Optional["Session"] = None) -> Optional["SysStatus"]:  # noqa: ARG001
    """获取当前 SysStatus 完整行 (id=1)

    返回 None 表示 id=1 行不存在 (极端脏数据) — 调用方应宽容 None。

    走 server.tables.SysStatus (兼容保留 db 参数但忽略)
    """
    from server.tables import SysStatus
    row = SysStatus.query_one(id=1)
    if row is None:
        return None
    # 保持 ORM 兼容: 返回的对象支持 .id/.trd_date/.status 等访问
    return row


class SysConfig(Base):
    """统一配置表

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
    diffs_json = Column(mysql.LONGTEXT, nullable=True, default="[]")
    broker_asset_json = Column(mysql.LONGTEXT, nullable=True, default="")
    local_asset_json = Column(mysql.LONGTEXT, nullable=True, default="")
    broker_positions_json = Column(mysql.LONGTEXT, nullable=True, default="")
    local_positions_json = Column(mysql.LONGTEXT, nullable=True, default="")
    rpc_status = Column(String(16), nullable=False, default="ok")  # ok / partial / failed
    error_message = Column(String(512), nullable=False, default="")
    created_by = Column(Integer, nullable=True)


# ─────────────── 行情 ───────────────

class QuoteSnapshot(Base):
    """行情快照

    📖 详见 `openspec/specs/data-model/spec.md` §4

    latest-only 模型（每 stock_code 1 行）。
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
    """序号生成器（多生成器，按 seq_name 分键）

    生成器: order_no（订单）/ task_batch（策略批次）
    📖 详见 `openspec/specs/data-model/spec.md` §5
    """
    __tablename__ = "order_no_seq"

    seq_name = Column(String(32), primary_key=True)
    last_value = Column(Integer, nullable=False, default=10000000)  # 8 位起
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)


# ─────────────── T0 任务表 ───────────────

class Stock(Base):
    """股票基础信息表（change slim-stocks-table）

    📖 详见 `openspec/specs/data-model/spec.md` §13 (stocks)

    仅保留 6 个业务字段（基础信息 + 交易粒度），删除 9 个未被消费的
    字段（industry/market/list_date/total_share/float_share/market_cap/pe_ratio/
    pb_ratio/intro），新增 3 个业务字段（is_t0_able/min_buy_qty/trade_unit）
    用于 admin 配置回转标志与买卖粒度。

    - stock_code 是 PK（与 quote_snapshots 一致,带 .SH/.SZ 后缀）
    - 0 个字段索引(sector 暂未加索引,数据量小可走全表扫)
    - updated_at 自动 ON UPDATE,用于增量 upsert 的"7 天内跳过"逻辑
    - 历史 14 字段数据已备份至 stocks_legacy 表
    - short_name 字段 (String(16), nullable): 拼音首字母简称(平安银行→PAYH),
      用于前端 autocomplete 首字母快速筛选;由 server/scripts/backfill_short_name.py
      一次性灌入,admin 手动维护,不走自动同步
    """
    __tablename__ = "stocks"

    stock_code = Column(String(16), primary_key=True, nullable=False)  # 000001.SZ
    stock_name = Column(String(64), nullable=False, default="")
    sector = Column(String(64), nullable=True)                # 板块(申万二级)
    is_t0_able = Column(Boolean, nullable=False, default=False)  # 是否支持 T+0 回转
    min_buy_qty = Column(Integer, nullable=False, default=100)  # 最小买入数量(A 股默认 100)
    trade_unit = Column(Integer, nullable=False, default=1)      # 买卖单位
    short_name = Column(String(16), nullable=True)              # 拼音首字母简称(平安银行→PAYH),admin 编辑/手动维护
    stktype = Column(SmallInteger, nullable=False, default=0)   # 证券类型 (0=股票 1=ETF),用户手动维护
    scale = Column(SmallInteger, nullable=False, default=2)     # 价格小数位精度 (2=A股 3=ETF),用于四舍五入
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)


class T0Task(Base):
    """T0 做 T 任务实体（change t0-task-management）

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
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)  # status 流转时自动更新
    closed_at = Column(DateTime, nullable=True)
