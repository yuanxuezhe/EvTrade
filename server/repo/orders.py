"""
repo/orders.py — orders 表仓库 + order_no_seq 表仓库（v13 从 services/ 迁入）

包含：
- 8 位订单序号生成器（next_order_no / get_current_no / reset_to）— 旧 services/order_no.py
- broker xtconstant 字典 + 委托 status 推断（ORDER_STATUS / TERMINAL_STATUSES /
  is_cancellable / _status_msg / _infer_order_status / _get_active_trd_date）— 旧 services/order_status.py
- v13 新增表级 CRUD 封装（get_by_order_no / insert_pending_order / insert_cancel_row）

规范：openspec/specs/rpc-protocol/spec.md REQ-RPC-009
      openspec/changes/2026-06-22-order-no-sqlite-compat (SQLite 3.21.0 兼容)
      openspec/changes/2026-07-06-layered-architecture-and-strategy-master (v13 分层)
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from server.models.orm import Order, SysStatus


# ================================================================
# 8 位订单序号生成器（v6 起 8 位单调递增；SQLite ≥ 3.21 三步分离）
# ================================================================

def next_order_no(db: Session) -> str:
    """原子自增，返回 8 位数字字符串。函数内自动 commit（破坏旧约定）。

    实现：三步分离（SQLite ≥ 3.21 兼容方案，2026-06-22 因 Python 3.6.8 自带
    SQLite 3.21.0 不支持 ON CONFLICT...DO UPDATE...RETURNING，从 2026-06-21
    提案的方案 A 降级）：
        1) INSERT OR IGNORE INTO order_no_seq ...  # 兜底初始化
        2) UPDATE order_no_seq SET last_value = last_value + 1 ...  # 自增
        3) SELECT last_value FROM order_no_seq ...  # 读出

    优势：
      1. 兼容当前 SQLite 3.21.0（业务不中断）
      2. 函数内 commit, 消除"调用方漏 commit 导致序号回退"风险
      3. SQLite 串行写入保证并发安全（无应用层锁）

    上限保护：8 位数字最大 99999999，达到上限时拒绝继续分配。

    注意：调用方不需要再 commit (函数已 commit)。
    """
    # 步 1: 兜底初始化 (id=1 不存在时插入 last_value=10000000)
    # v18 修复 MySQL 兼容: (a) `last_value` 是 MySQL 8.0 保留字必须反引号包裹
    #                       (b) `INSERT OR IGNORE` 是 sqlite 方言，MySQL 是 `INSERT IGNORE`
    bind = db.get_bind()
    is_mysql = bind.dialect.name == "mysql"
    if is_mysql:
        db.execute(text("""
            INSERT IGNORE INTO order_no_seq (`id`, `last_value`, `updated_at`)
            VALUES (1, 10000000, CURRENT_TIMESTAMP)
        """))
    else:
        db.execute(text("""
            INSERT OR IGNORE INTO order_no_seq (`id`, `last_value`, `updated_at`)
            VALUES (1, 10000000, CURRENT_TIMESTAMP)
        """))
    # 步 2: 自增
    db.execute(text("""
        UPDATE order_no_seq
        SET `last_value` = `last_value` + 1, `updated_at` = CURRENT_TIMESTAMP
        WHERE `id` = 1
    """))
    # 步 3: 读出
    val = db.execute(text(
        "SELECT `last_value` FROM order_no_seq WHERE `id` = 1"
    )).scalar()
    if val is None:
        raise RuntimeError("order_no_seq 读取失败")
    if val >= 99999999:
        raise RuntimeError(
            f"order_no 已达上限 ({val})，请手动扩容或迁移新序号段"
        )
    db.commit()
    return str(val)


def get_current_no(db: Session) -> int:
    """查询当前序号（不递增）"""
    row = db.execute(text("SELECT last_value FROM order_no_seq WHERE id = 1")).first()
    if not row:
        return 10000000
    return row[0]


def reset_to(db: Session, value: int) -> None:
    """重置序号（仅测试/迁移用）"""
    db.execute(text("""
        UPDATE order_no_seq SET last_value = :v, updated_at = CURRENT_TIMESTAMP WHERE id = 1
    """), {"v": value})
    db.commit()


# ================================================================
# broker xtconstant 字典（v11, 1:1 对齐）
# 权威源: iquant/xtquant_api.py 第 130-200 行 / 280-340 行
# ================================================================
ORDER_STATUS = {
    "48":  "未报",          # ORDER_UNREPORTED
    "49":  "待报",          # ORDER_WAIT_REPORTING
    "50":  "已报",          # ORDER_REPORTED
    "51":  "已报待撤",      # ORDER_REPORTED_CANCEL
    "52":  "部成待撤",      # ORDER_PARTSUCC_CANCEL
    "53":  "部成部撤",      # ORDER_PART_CANCEL
    "54":  "已撤",          # ORDER_CANCELED
    "55":  "部成",          # ORDER_PART_SUCC
    "56":  "已成",          # ORDER_SUCCEEDED
    "57":  "废单",          # ORDER_JUNK
    "255": "未知",          # ORDER_UNKNOWN
}

# 终态集合（v11: 含 broker 52=部成待撤, 删 broker 55=部成 PART_SUCC 非终态 - 与 broker 终态口径一致）
# 含 broker 52 (部成待撤, 撤单过渡) + broker 53/54/56/57 (部成部撤/已撤/已成/废单)
# 不含 broker 55 (PART_SUCC 部成, 可继续累计到 broker 56 已成)
TERMINAL_STATUSES = ('52', '53', '54', '56', '57')


def is_cancellable(code: str) -> bool:
    """是否可撤单（v11: 含 broker 50=已报 也可撤）

    触发码 (48, 49, 50) 对应 broker UNREPORTED / WAIT_REPORTING / REPORTED.
    broker 51=已报待撤 已算"撤单中", 不再可发起新撤单.
    """
    return code in ('48', '49', '50')


def _status_msg(status: str) -> str:
    """状态码 → 中文 (broker xtconstant 字典)"""
    return ORDER_STATUS.get(status, '')


def _infer_order_status(order: Order, broker_status: Optional[str] = None) -> str:
    """委托 status 本地推断（v8 改: cancelled_volume 主轴 + v11 改: broker 码输出）

    Args:
        order: Order 实例, 需要 traded_volume / cancelled_volume / volume / status (当前值) 字段
        broker_status: 可选, broker ord_cfm 推的 status 字段 (52/53/54 视为撤单类, broker xtconstant 码)
                     trd_cfm 调用时传 None (trd_cfm 永远不写撤单类状态)

    Returns:
        推断后的 status: 50 / 53 / 54 / 55 / 56 (broker xtconstant 码全集)

    规则 (v8 cancelled_volume 主轴 + v11 broker 码输出):
      1. 当前 status 已是终态 (52/53/54/56/57, 不含 broker 55=部成 PART_SUCC 非终态) → 保持, 不再推断
         (避免 trd_cfm 累计覆盖 ord_cfm 写的撤单终态; broker 55=部成 仍可继续累计到 broker 56 已成)
      2. 撤单主轴 (cum_cancelled):
         - cum_cancelled >= vol                 → 54 (broker 已撤)
         - cum_cancelled > 0 && cum_traded > 0  → 53 (broker 部成部撤)
         - cum_cancelled > 0                    → 54 (部分撤单无成交, 也视作已撤)
      3. broker_status 给出且在 (52, 53, 54) → 撤单类信号 (兼容老 broker 协议)
         - cum_traded = 0                       → 54 (broker 已撤)
         - 0 < cum_traded < vol                 → 53 (broker 部成部撤)
         - cum_traded = vol                     → 56 (broker 已成)
      4. 累计推断 (cum_traded)
         - cum_traded = 0                       → 50 (broker 已报)
         - 0 < cum_traded < vol                 → 55 (broker 部成)
         - cum_traded = vol                     → 56 (broker 已成)
    """
    current = order.status or '48'

    # 1. 终态保持
    if current in TERMINAL_STATUSES:
        return current

    cum = order.traded_volume or 0
    cum_cancelled = order.cancelled_volume or 0
    vol = order.volume or 0

    # 2. 撤单主轴 (v8 新增, 优先于 broker_status 判定)
    if cum_cancelled >= vol and vol > 0:
        return '54'  # broker 已撤: 撤单数 ≥ 委托数
    if cum_cancelled > 0 and cum > 0:
        return '53'  # broker 部成部撤: 既有成交又有撤单
    if cum_cancelled > 0 and cum == 0:
        return '54'  # 部分撤单 (无成交) → 视作 broker 已撤 (运营角度)

    # 3. broker 推了撤单类 status (兼容老 broker 协议, 无 cancelled_volume 字段时)
    # v11: 触发码含 broker 51=已报待撤 (broker 撤单类全集: 51/52/53/54)
    if broker_status and broker_status in ('51', '52', '53', '54'):
        if cum == 0:
            return '54'
        if cum < vol:
            return '53'
        return '56'  # broker 已成, broker 撤单无意义

    # 4. 累计推断 (v11 broker 码)
    if cum == 0:
        return '50'  # broker 已报
    if cum < vol:
        return '55'  # broker 部成
    return '56'  # broker 已成


def _get_active_trd_date(db: Session) -> str:
    """获取当前激活交易日；未激活则用 MAX(trd_date)"""
    row = db.query(SysStatus).filter_by(status='active').first()
    if row:
        return row.trd_date
    for table in ("orders", "trades", "positions", "reconcile_report"):
        r = db.execute(text(f"SELECT MAX(trd_date) FROM {table}")).first()
        if r and r[0]:
            return r[0]
    return datetime.now().strftime('%Y%m%d')


# ================================================================
# v13 NEW: 表级 CRUD 封装（orders 表）
# ================================================================

def get_by_order_no(db: Session, trd_date: str, order_no: str) -> Optional[Order]:
    """按 (trd_date, order_no) 复合主键查询 orders 行。"""
    return db.query(Order).filter_by(trd_date=trd_date, order_no=order_no).first()


def insert_pending_order(
    db: Session,
    *,
    trd_date: str,
    order_no: str,
    user_def: str,
    stock_code: str,
    order_type: str,
    price_type: str,
    price: float,
    volume: int,
) -> Order:
    """INSERT status=48 待报行（place 第 3 步用；user_def 透传 = str(strategy.id) / 'T0' / 默认空）。

    函数内 commit + refresh，返回 ORM 实例供 caller 继续 UPDATE。
    """
    from server.utils.time import format_ts  # 避免循环 import
    order = Order(
        trd_date=trd_date,
        order_no=order_no,
        user_def=user_def,
        stock_code=stock_code,
        order_type=order_type,
        price_type=price_type,
        price=price,
        volume=volume,
        traded_volume=0, traded_amount=0.0, avg_price=0.0,
        status="48", status_msg="未报",
        order_time=format_ts(tz='local'),
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def insert_cancel_row(
    db: Session,
    *,
    orig: Order,
    cancel_order_no: str,
    raw_id: Optional[str] = None,
) -> Order:
    """INSERT cancel-row（v9 重构: order_flag=1, user_def='CANCEL:{orig.order_no}'）。

    v13 加 raw_id 参数（默认 None；DELETE 端点调用时传 orig.order_no）。
    普通 strategy 委托的 raw_id 永远为 NULL（place 流程不调本函数）。

    函数内 commit + refresh。
    """
    from server.utils.time import format_ts  # 避免循环 import
    cancel_row = Order(
        trd_date=orig.trd_date,
        order_no=cancel_order_no,
        order_id=None,                    # broker 永远不报这个 row
        user_def="CANCEL:{}".format(orig.order_no),  # 关联: cancel → orig
        raw_id=raw_id,                    # ★ v13 NEW 字段写入
        stock_code=orig.stock_code,       # 镜像
        order_type=orig.order_type,       # 镜像 23/24
        price_type=orig.price_type,       # 镜像
        price=orig.price,                 # 镜像
        volume=0,                          # ★ 用户选择: 零委托量
        traded_volume=0, traded_amount=0.0, avg_price=0.0,
        cancelled_volume=0,
        order_flag=1,                      # ★ 撤单委托标记
        status="48",                       # sentinel 待发
        status_msg="撤单请求中",
        order_time=format_ts(tz='local'),
    )
    db.add(cancel_row)
    db.commit()
    db.refresh(cancel_row)
    return cancel_row
