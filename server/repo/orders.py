"""
repo/orders.py — orders 表仓库 + order_no_seq 表仓库

包含:
- 8 位订单序号生成器 (next_order_no / get_current_no / reset_to)
- broker xtconstant 字典 + 委托 status 推断 (ORDER_STATUS / TERMINAL_STATUSES /
  is_cancellable / _status_msg / _infer_order_status / _get_active_trd_date)
- 表级 CRUD 封装 (get_by_order_no / insert_pending_order / insert_cancel_row)
- DB 访问走 server/tables/ 层: 用 Orders.add_one / Orders.query_one / Orders.update_one 等标准接口

规范: openspec/specs/rpc-protocol/spec.md REQ-RPC-009
      openspec/changes/2026-06-22-order-no-sqlite-compat (SQLite 3.21.0 兼容)
      openspec/changes/2026-07-06-layered-architecture-and-strategy-master (分层)
      openspec/changes/2026-07-23-tables-codegen-and-orm-removal (tables 层)
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import text

from server.tables.base import get_conn
from server.tables.order_no_seq import OrderNoSeq
from server.tables.orders import Orders
from server.tables.sys_status import SysStatus
from server.tables.trades import Trades
from server.tables.positions import Positions
from server.tables.reconcile_report import ReconcileReport


# ================================================================
# 8 位订单序号生成器 (8 位单调递增; SQLite ≥ 3.21 三步分离)
# ================================================================

def next_seq(name: str, db=None) -> str:
    """按 seq_name 分键的原子自增序号生成器.

    3 步分离方案 (SQLite ≥ 3.21 兼容), 按 `seq_name` 分键:
        1) INSERT IGNORE INTO order_no_seq (seq_name, last_value, updated_at) ...  # 兜底初始化
        2) UPDATE ... SET last_value = last_value + 1 WHERE seq_name = :name ...   # 自增
        3) SELECT last_value ...                                                  # 读出

    函数内 commit (沿用旧约定), 调用方不需要再 commit.
    上限保护: 8 位数字最大 99999999, 达到上限时拒绝继续分配.
    db 参数保留 (兼容旧调用方: next_seq(db, name)), 实际依赖 tables 层 get_conn().
    """
    with get_conn() as conn:
        # 步 1: 兜底初始化 (生成器行不存在时插入 last_value=10000000)
        # `last_value` 是 MySQL 8.0 保留字必须反引号包裹
        conn.execute(text("""
            INSERT IGNORE INTO `order_no_seq` (`seq_name`, `last_value`, `updated_at`)
            VALUES (:name, 10000000, CURRENT_TIMESTAMP)
        """), {"name": name})
        # 步 2: 自增 (单 UPDATE 保证原子性)
        conn.execute(text("""
            UPDATE `order_no_seq`
            SET `last_value` = `last_value` + 1, `updated_at` = CURRENT_TIMESTAMP
            WHERE `seq_name` = :name
        """), {"name": name})
        conn.commit()
        # 步 3: 读出 (新事务里读, 不加锁)
        val = conn.execute(text(
            "SELECT `last_value` FROM `order_no_seq` WHERE `seq_name` = :name"
        ), {"name": name}).scalar()
    if val is None:
        raise RuntimeError(f"seq '{name}' 读取失败")
    if val >= 99999999:
        raise RuntimeError(
            f"seq '{name}' 已达上限 ({val}), 请手动扩容或迁移新序号段"
        )
    return str(val)


def next_order_no(db=None) -> str:
    """原子自增, 返回 8 位数字字符串. 函数内自动 commit (破坏旧约定).

    实现: 委托通用序号生成器 next_seq(db, 'order_no'),
    行为: order_no 生成器行初值 10000000, 每次 +1, 8 位上限.

    上限保护: 8 位数字最大 99999999, 达到上限时拒绝继续分配.

    OrderNoSeq.query_one 不会锁, 所以保留 SELECT FOR UPDATE 写法 (绕过
    TableBase 标准方法). 函数内 commit, 调用方不需要再 commit.
    db 参数保留 (兼容旧调用方: next_order_no(db)), 实际不依赖 db.
    """
    return next_seq('order_no', db)


def get_current_no(db=None) -> int:
    """查询当前序号 (不递增). 用 OrderNoSeq.query_one, 键 seq_name='order_no'."""
    row = OrderNoSeq.query_one(seq_name='order_no')
    if not row:
        return 10000000
    return row.last_value


def reset_to(db=None, value: int = 0) -> None:
    """重置序号 (仅测试/迁移用). 用 OrderNoSeq.update_one, 键 seq_name='order_no'."""
    OrderNoSeq.update_one(
        {"last_value": value, "updated_at": datetime.now()},
        seq_name='order_no',
    )


# ================================================================
# broker xtconstant 字典 (1:1 对齐)
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

# 终态集合 (与 broker 终态口径一致)
# 含 broker 52 (部成待撤, 撤单过渡) + broker 53/54/56/57 (部成部撤/已撤/已成/废单)
# 不含 broker 55 (PART_SUCC 部成, 可继续累计到 broker 56 已成)
TERMINAL_STATUSES = ('52', '53', '54', '56', '57')


def is_cancellable(code: str) -> bool:
    """是否可撤单 (仅 已报 50 / 部成 55)

    规则: (50, 55) - 仅 已报/部成 可撤
      - 48 未报 / 49 待报: broker order_id 未回报, 禁止撤单
      - 50 已报: broker 已接收, 可撤
      - 55 部成: 剩余未成交部分可撤
      - 51/52 已报待撤/部成待撤: 已在撤单流程中, 不可再发起新撤单
      - 53/54/56/57 终态: 不可撤
    """
    return code in ('50', '55')


def _status_msg(status: str) -> str:
    """状态码 → 中文 (broker xtconstant 字典)"""
    return ORDER_STATUS.get(status, '')


def _infer_order_status(order, broker_status: Optional[str] = None) -> str:
    """委托 status 本地推断 (cancelled_volume 主轴 + broker 码输出)

    参数 order 兼容 Order ORM 实例 和 server.tables.orders.Row (两者都支持
    属性访问 .status / .traded_volume / .cancelled_volume / .volume).

    Args:
        order: Order ORM 实例 或 server.tables.orders.Row, 需要 traded_volume /
               cancelled_volume / volume / status (当前值) 字段
        broker_status: 可选, broker ord_cfm 推的 status 字段 (52/53/54 视为撤单类, broker xtconstant 码)
                     trd_cfm 调用时传 None (trd_cfm 永远不写撤单类状态)

    Returns:
        推断后的 status: 50 / 53 / 54 / 55 / 56 (broker xtconstant 码全集)

    规则 (cancelled_volume 主轴 + broker 码输出):
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

    # 2. 撤单主轴 (优先于 broker_status 判定)
    if cum_cancelled >= vol and vol > 0:
        return '54'  # broker 已撤: 撤单数 ≥ 委托数
    if cum_cancelled > 0 and cum > 0:
        return '53'  # broker 部成部撤: 既有成交又有撤单
    if cum_cancelled > 0 and cum == 0:
        return '54'  # 部分撤单 (无成交) → 视作 broker 已撤 (运营角度)

    # 3. broker 推了撤单类 status (兼容老 broker 协议, 无 cancelled_volume 字段时)
    # 触发码含 broker 51=已报待撤 (broker 撤单类全集: 51/52/53/54)
    if broker_status and broker_status in ('51', '52', '53', '54'):
        if cum == 0:
            return '54'
        if cum < vol:
            return '53'
        return '56'  # broker 已成, broker 撤单无意义

    # 4. 累计推断 (broker 码)
    if cum == 0:
        return '50'  # broker 已报
    if cum < vol:
        return '55'  # broker 部成
    return '56'  # broker 已成


def _get_active_trd_date(db=None) -> str:
    """获取当前激活交易日; 未激活则用 MAX(trd_date)

    用 SysStatus.query_one(id=1) + 全表扫描 Python max.
    db 参数保留 (兼容旧调用方: _get_active_trd_date(db)), 实际不依赖 db.
    """
    # sys_status 是单行配置, 主键查询
    ss = SysStatus.query_one(id=1)
    if ss and ss.trd_date:
        return ss.trd_date
    # 兜底: 各表全查取最大 trd_date (数据量小, 全查无压力)
    candidates = []
    for rows in (
        Orders.query_all(),       # 47 行
        Trades.query_all(),       # 几十行
        Positions.query_all(),
        ReconcileReport.query_all(),
    ):
        for r in rows:
            td = getattr(r, "trd_date", None)
            if td:
                candidates.append(td)
    if candidates:
        return max(candidates)
    return datetime.now().strftime('%Y%m%d')


# ================================================================
# 表级 CRUD 封装 (orders 表) — 走 Orders 标准方法
# ================================================================

def get_by_order_no(db=None, trd_date: str = '', order_no: str = '') -> Optional[object]:
    """按 (trd_date, order_no) 复合主键查询 orders 行.

    用 Orders.query_one (复合主键). 返回 server.tables.orders.Row (非 ORM Order).
    db 参数保留 (兼容旧调用方).
    """
    return Orders.query_one(trd_date=trd_date, order_no=order_no)


def insert_pending_order(
    db=None,
    *,
    trd_date: str,
    order_no: str,
    user_def: str,
    stock_code: str,
    order_type: str,
    price_type: str,
    price: float,
    volume: int,
) -> object:
    """INSERT status=48 待报行 (place 第 3 步用; user_def 透传 = str(strategy.id) / 'T0' / 默认空).

    用 Orders.add_one. 返回 server.tables.orders.Row.
    db 参数保留 (兼容旧调用方: insert_pending_order(db, ...)).
    """
    from server.utils.time import format_ts  # 避免循环 import
    return Orders.add_one({
        "trd_date": trd_date,
        "order_no": order_no,
        "user_def": user_def,
        "stock_code": stock_code,
        "order_type": order_type,
        "price_type": price_type,
        "price": price,
        "volume": volume,
        "traded_volume": 0,
        "traded_amount": 0.0,
        "avg_price": 0.0,
        "status": "48",
        "status_msg": "待报",   # 统一为"待报" (broker 异步反馈前)
        "order_time": format_ts(tz='local'),
    })


def insert_cancel_row(
    db=None,
    *,
    orig,                       # server.tables.orders.Row
    cancel_order_no: str,
    raw_id: Optional[str] = None,
) -> object:
    """INSERT cancel-row (order_flag=1, user_def='CANCEL:{orig.order_no}').

    raw_id 参数 (默认 None; DELETE 端点调用时传 orig.order_no).
    普通 strategy 委托的 raw_id 永远为 NULL (place 流程不调本函数).

    用 Orders.add_one. orig 是 Row (属性访问兼容).
    返回 server.tables.orders.Row.
    db 参数保留 (兼容旧调用方).
    """
    from server.utils.time import format_ts  # 避免循环 import
    return Orders.add_one({
        "trd_date": orig.trd_date,
        "order_no": cancel_order_no,
        "order_id": None,                     # broker 永远不报这个 row
        "user_def": "CANCEL:{}".format(orig.order_no),  # 关联: cancel → orig
        "raw_id": raw_id,                     # ★ raw_id 字段写入
        "stock_code": orig.stock_code,        # 镜像
        "order_type": orig.order_type,        # 镜像 23/24
        "price_type": orig.price_type,        # 镜像
        "price": orig.price,                  # 镜像
        "volume": 0,                          # ★ 用户选择: 零委托量
        "traded_volume": 0,
        "traded_amount": 0.0,
        "avg_price": 0.0,
        "cancelled_volume": 0,
        "order_flag": 1,                      # ★ 撤单委托标记
        "status": "48",                       # sentinel 待发
        "status_msg": "撤单请求中",
        "order_time": format_ts(tz='local'),
    })