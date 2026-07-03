"""
test_push_handlers.py — v6 推送落库验证（order-pk-by-orderno）

v6 改动:
- ord_cfm 用 broker.remark (= order_no) 匹配本地 Order,只填 order_id + 推断 status
- ord_cfm 不再更新 traded_volume (那是 trd_cfm 的事)
- trd_cfm 用 remark 匹配 Order,累加 + 推断 status
- 委托 status 统一由 _infer_order_status 本地推断(不再直接抄 broker 推的 status)
"""
import pytest
import logging
from datetime import datetime
from server.db import Base, engine, init_db, SessionLocal
from server.models.orm import Order, Trade, SysStatus, Position
from server.services.push.handlers import handle_push, _infer_order_status, TERMINAL_STATUSES, _status_msg

@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(bind=engine)
    init_db()
    db = SessionLocal()
    db.add(SysStatus(trd_date="20260614", status="active"))
    db.commit()
    db.close()
    yield

# ──── _infer_order_status 状态推断矩阵 ────

def test_infer_status_48_with_zero_volume():
    """broker 推 48(待报) + 累计=0 + 非终态 → 推断 50(broker 已报, v11)"""
    o = Order(volume=1000, traded_volume=0, status="48")
    assert _infer_order_status(o, broker_status="48") == "50"

def test_infer_status_49_with_zero_volume():
    """broker 推 49(已报) + 累计=0 + 非终态 → 50(broker 已报, v11)"""
    o = Order(volume=1000, traded_volume=0, status="48")
    assert _infer_order_status(o, broker_status="49") == "50"

def test_infer_status_52_with_zero_volume():
    """broker 推 52(部撤) + 累计=0 + 非终态 → 54(broker 已撤, v11)"""
    o = Order(volume=1000, traded_volume=0, status="48")
    assert _infer_order_status(o, broker_status="52") == "54"

def test_infer_status_53_with_zero_volume():
    """broker 推 53(部成部撤) + 累计=0 → 54(broker 已撤, v11)"""
    o = Order(volume=1000, traded_volume=0, status="48")
    assert _infer_order_status(o, broker_status="53") == "54"

def test_infer_status_52_with_partial_volume():
    """broker 推 52(部成待撤) + 累计<volume → 53(broker 部成部撤, v11)"""
    o = Order(volume=1000, traded_volume=500, status="50")
    assert _infer_order_status(o, broker_status="52") == "53"

def test_infer_status_53_with_full_volume():
    """broker 推 53(部成部撤) + 累计=volume → 56(broker 已成, v11)"""
    o = Order(volume=1000, traded_volume=1000, status="50")
    assert _infer_order_status(o, broker_status="53") == "56"

def test_infer_status_trd_cfm_partial():
    """trd_cfm 累计后(不传 broker_status) → 55(broker 部成, v11)"""
    o = Order(volume=1000, traded_volume=300, status="49")
    assert _infer_order_status(o, broker_status=None) == "55"

def test_infer_status_trd_cfm_full():
    """trd_cfm 累计到 volume → 56(broker 已成, v11: 替代旧 51=local 已成)"""
    o = Order(volume=1000, traded_volume=1000, status="50")
    assert _infer_order_status(o, broker_status=None) == "56"

def test_infer_status_terminal_54_not_overridden():
    """v11: 终态 54(broker 已撤)被 trd_cfm 累计时保持(v11 替代旧 51=local 已成 测试, broker 51=已报待撤 非终态)"""
    o = Order(volume=1000, traded_volume=0, status="54")  # broker 已撤 终态
    assert _infer_order_status(o, broker_status=None) == "54"

def test_infer_status_terminal_56_not_overridden():
    """终态 56(broker 已成)被 trd_cfm 累计时保持"""
    o = Order(volume=1000, traded_volume=200, status="56")
    assert _infer_order_status(o, broker_status=None) == "56"

def test_infer_status_terminal_53_not_overridden():
    """终态 53(broker 部成部撤)被 ord_cfm 再推时也保持"""
    o = Order(volume=1000, traded_volume=0, status="53")
    # broker 又推 49 也不覆盖
    assert _infer_order_status(o, broker_status="49") == "53"

# ──── ord_cfm ────

def test_ord_cfm_fills_order_id_via_remark():
    """v6: ord_cfm 通过 broker.remark (= order_no) 匹配本地 Order,填入 broker order_id

    本地 Order 初始 order_id=None(下单时 broker 还没回报)
    ord_cfm 到达后写入 broker 真实 order_id
    """
    db = SessionLocal()
    db.add(Order(
        trd_date="20260614",
        order_id=None,  # v6: 下单时 broker 还没回报
        user_def="CID-1", order_no="10000001",
        stock_code="600030.SH", order_type="23", price_type=11, price=12.5, volume=100,
        status="48",  # 待报
    ))
    db.commit()
    db.close()

    db = SessionLocal()
    handle_push(db, "ord_cfm", {
        "order_id": "BROKER-OID-1",
        "remark": "10000001",   # ← broker 透传回来的 order_no
        "order_status": "49",    # v10: broker 原字段名
    }, ts="20260614 09:30:01")
    db.commit()
    row = db.query(Order).filter_by(order_no="10000001", trd_date="20260614").first()
    assert row.order_id == "BROKER-OID-1"
    # status 由 _infer_order_status 推断:broker_status=49 + 累计=0 + 非终态 → 50(broker 已报)
    assert row.status == "50"
    db.close()

def test_ord_cfm_does_not_update_traded_volume():
    """v6: ord_cfm 不更新 traded_volume(那是 trd_cfm 的事)"""
    db = SessionLocal()
    db.add(Order(
        trd_date="20260614",
        order_id="OID-PART", user_def="CID-PART", order_no="10000002",
        stock_code="600030.SH", order_type="23", price_type=11, price=12.5, volume=100,
        status="49",
        traded_volume=0, traded_amount=0.0, avg_price=0.0,
    ))
    db.commit()
    db.close()

    db = SessionLocal()
    handle_push(db, "ord_cfm", {
        "order_id": "OID-PART",
        "remark": "10000002",
        "order_status": "50",  # v10: broker 原字段名, broker 推部成
        "traded_volume": 30,      # 即使 broker 推了也忽略
        "traded_amount": 375.0,
        "traded_price": 12.5,
    }, ts="20260614 09:31:00")
    db.commit()
    row = db.query(Order).filter_by(order_id="OID-PART", trd_date="20260614").first()
    # v6: traded_* 不被 ord_cfm 覆盖
    assert row.traded_volume == 0
    assert row.traded_amount == 0.0
    assert row.avg_price == 0.0
    # status 由 _infer_order_status 推断:broker_status=50 + 累计=0 + 非终态 → 50(broker 已报, v11)
    assert row.status == "50"
    db.close()

def test_ord_cfm_infers_status_53_when_broker_pushed_cancel():
    """broker ord_cfm 推 53(部成部撤) + 累计=0 → 推断 54(broker 已撤, v11)"""
    db = SessionLocal()
    db.add(Order(
        trd_date="20260614",
        order_id="OID-CXL", user_def="CID-CXL", order_no="10000003",
        stock_code="600030.SH", order_type="23", price_type=11, price=12.5, volume=100,
        status="49", traded_volume=0,
    ))
    db.commit()
    db.close()

    db = SessionLocal()
    handle_push(db, "ord_cfm", {
        "order_id": "OID-CXL",
        "remark": "10000003",
        "order_status": "53",  # v10: broker 原字段名
    }, ts="20260614 10:00:00")
    db.commit()
    row = db.query(Order).filter_by(order_id="OID-CXL", trd_date="20260614").first()
    assert row.status == "54"  # broker 已撤 (v11)
    db.close()

def test_ord_cfm_logs_warn_when_no_local_order():
    """push 来了但本地无对应 Order → 打 WARN 不创建"""
    db = SessionLocal()
    handle_push(db, "ord_cfm", {
        "order_id": "GHOST-OID",
        "remark": "99999999",  # 不存在的 order_no
        "order_status": "49",  # v10: broker 原字段名
    }, ts="20260614 09:30:00")
    db.commit()
    # 不会有新行
    assert db.query(Order).count() == 0
    db.close()

# ──── trd_cfm ────

def test_trd_cfm_inserts_trade_and_updates_order_via_remark():
    """v6: trd_cfm 用 broker.remark (= order_no) 匹配 Order

    v10: 严格用 broker 原字段名 traded_id / traded_price / traded_volume / traded_amount / traded_time
    """
    db = SessionLocal()
    db.add(Order(
        trd_date="20260614",
        order_id="OID-T", user_def="CID-T", order_no="10000010",
        stock_code="600030.SH", order_type="23", price_type=11, price=12.5, volume=100,
        status="49", traded_volume=0, traded_amount=0,
    ))
    db.commit()
    db.close()

    db = SessionLocal()
    handle_push(db, "trd_cfm", {
        "traded_id": "TID-001",       # v10: 原字段名
        "order_id": "OID-T",
        "remark": "10000010",  # ← v6: 关键,用来匹配本地 Order
        "stock_code": "600030.SH",
        "order_type": "23",
        "traded_price": 12.5,         # v10: 原字段名
        "traded_volume": 30,          # v10: 原字段名
        "traded_amount": 375.0,       # v10: 原字段名
        "traded_time": "09:31:00",    # v10: 原字段名
    }, ts="20260614 09:31:00")
    db.commit()

    t = db.query(Trade).filter_by(trade_id="TID-001", order_no="10000010", trd_date="20260614").first()
    assert t is not None
    assert t.stock_code == "600030.SH"
    assert t.volume == 30
    assert t.price == 12.5
    assert t.trd_date == "20260614"

    # Order 累计更新
    o = db.query(Order).filter_by(order_no="10000010", trd_date="20260614").first()
    assert o.traded_volume == 30
    assert o.traded_amount == 375.0
    assert o.avg_price == 12.5
    # status 由 _infer_order_status 推断:累计=30 < volume=100 + 非终态 → 55(broker 部成, v11)
    assert o.status == "55"
    db.close()

def test_ord_cfm_flattens_cancelled_on_broker_reject_without_volume_field():
    """change system-delegation-price-fill-calc: R2b broker 推回废单类 status 且未推 cancelled_volume 字段时本地兜底抹平"""
    db = SessionLocal()
    db.add(Order(
        trd_date="20260614",
        order_id="OID-R2B", user_def="CID-R2B", order_no="10000040",
        stock_code="600030.SH", order_type="23", price_type=11, price=12.5, volume=100,
        status="49", cancelled_volume=0,
    ))
    db.commit()
    db.close()

    db = SessionLocal()
    handle_push(db, "ord_cfm", {
        "order_id": "OID-R2B",
        "remark": "10000040",
        "order_status": "55",       # broker 推废单
        # 故意不推 cancelled_volume / cancel_volume / withdrawn_volume
    }, ts="20260614 09:40:00")
    db.commit()

    o = db.query(Order).filter_by(order_no="10000040", trd_date="20260614").first()
    assert o is not None
    assert o.cancelled_volume == 100  # R2b 兜底抹平
    db.close()


def test_ord_cfm_does_not_flatten_when_broker_cancelled_field_present():
    """change: Q3 选 b 信 broker —— 当 broker 推了 cancelled_volume 字段时按累加 + 截断，不走 R2b 兜底"""
    db = SessionLocal()
    db.add(Order(
        trd_date="20260614",
        order_id="OID-NOR2B", user_def="CID-NOR2B", order_no="10000041",
        stock_code="600030.SH", order_type="23", price_type=11, price=12.5, volume=100,
        status="49", cancelled_volume=10,
    ))
    db.commit()
    db.close()

    db = SessionLocal()
    handle_push(db, "ord_cfm", {
        "order_id": "OID-NOR2B",
        "remark": "10000041",
        "order_status": "55",
        "cancelled_volume": 10,  # broker 推 10 → 累加 10, 不走 R2b 兜底
    }, ts="20260614 09:41:00")
    db.commit()

    o = db.query(Order).filter_by(order_no="10000041", trd_date="20260614").first()
    assert o.cancelled_volume == 20  # 10 + 10 = 20 (累加,不抹平)
    db.close()


def test_trd_cfm_amount_local_calc_ignores_broker_traded_amount():
    """change system-delegation-price-fill-calc: trades.amount 本地算 price × volume,
    broker 推 traded_amount=999 (与本地算不一致) 时不入表。
    """
    db = SessionLocal()
    db.add(Order(
        trd_date="20260614",
        order_id="OID-LC", user_def="CID-LC", order_no="10000030",
        stock_code="600030.SH", order_type="23", price_type=11, price=10.0, volume=200,
        status="49", traded_volume=0, traded_amount=0,
    ))
    db.commit()
    db.close()

    db = SessionLocal()
    handle_push(db, "trd_cfm", {
        "traded_id": "TID-LC",
        "order_id": "OID-LC",
        "remark": "10000030",
        "stock_code": "600030.SH",
        "order_type": "23",
        "traded_price": 12.5,
        "traded_volume": 100,
        "traded_amount": 999.99,    # broker 推的金额（与本地 price×volume 不一致），期望被丢弃
        "traded_time": "09:31:00",
    }, ts="20260614 09:31:00")
    db.commit()

    t = db.query(Trade).filter_by(trade_id="TID-LC", order_no="10000030", trd_date="20260614").first()
    assert t is not None
    # 本地算: 12.5 × 100 = 1250, broker 推 999.99 不被采纳
    assert t.amount == 1250.0

    o = db.query(Order).filter_by(order_no="10000030", trd_date="20260614").first()
    # 累计也按本地算的金额
    assert o.traded_volume == 100
    assert o.traded_amount == 1250.0
    assert o.avg_price == 12.5
    db.close()


def test_trd_cfm_amount_zero_when_volume_zero():
    """change: trade.volume = 0 时 amount = 0 (price × volume)，
    avg_price 不变（仅防除零守卫）。
    """
    db = SessionLocal()
    db.add(Order(
        trd_date="20260614",
        order_id="OID-ZV", user_def="CID-ZV", order_no="10000031",
        stock_code="600030.SH", order_type="23", price_type=11, price=12.5, volume=200,
        status="50", traded_volume=50, traded_amount=625.0, avg_price=12.5,
    ))
    db.commit()
    db.close()

    db = SessionLocal()
    handle_push(db, "trd_cfm", {
        "traded_id": "TID-ZV",
        "order_id": "OID-ZV",
        "remark": "10000031",
        "stock_code": "600030.SH",
        "order_type": "23",
        "traded_price": 12.5,
        "traded_volume": 0,
        # broker 怪异: amount 字段存在但 price/volume 中任一为 0
        "traded_amount": 999.0,
    }, ts="20260614 09:33:00")
    db.commit()

    t = db.query(Trade).filter_by(trade_id="TID-ZV", order_no="10000031", trd_date="20260614").first()
    assert t is not None
    assert t.volume == 0
    assert t.amount == 0.0

    o = db.query(Order).filter_by(order_no="10000031", trd_date="20260614").first()
    # 累计后 volume 不变,amount 不变,avg_price 不被改写为 NaN
    assert o.traded_volume == 50
    assert o.traded_amount == 625.0
    assert o.avg_price == 12.5  # 保留原值
    db.close()


def test_trd_cfm_fills_status_to_51_when_full():
    """trd_cfm 累计到 volume → 51(已成)

    v10: 严格用 broker 原字段名 traded_id / traded_price / traded_volume / traded_amount
    """
    db = SessionLocal()
    db.add(Order(
        trd_date="20260614",
        order_id="OID-FULL", user_def="CID-FULL", order_no="10000011",
        stock_code="600030.SH", order_type="23", price_type=11, price=12.5, volume=100,
        status="50", traded_volume=50, traded_amount=625.0,
    ))
    db.commit()
    db.close()

    db = SessionLocal()
    handle_push(db, "trd_cfm", {
        "traded_id": "TID-002",       # v10: 原字段名
        "order_id": "OID-FULL",
        "remark": "10000011",
        "stock_code": "600030.SH",
        "traded_price": 12.5, "traded_volume": 50, "traded_amount": 625.0,  # v10: 原字段名
    }, ts="20260614 09:32:00")
    db.commit()
    o = db.query(Order).filter_by(order_no="10000011", trd_date="20260614").first()
    assert o.traded_volume == 100
    assert o.status == "56"  # broker 已成 (v11: 替代旧 '51' local 已成)
    db.close()

def test_trd_cfm_idempotent():
    """同 traded_id 二次推送 → 不会重复插入 + 不会重复累计

    v10: 严格用 broker 原字段名 traded_id / traded_price / traded_volume / traded_amount
    """
    db = SessionLocal()
    db.add(Order(
        trd_date="20260614",
        order_id="OID-IDEM", user_def="CID-IDEM", order_no="10000020",
        stock_code="600030.SH", order_type="23", price_type=11, price=12.5, volume=100,
        status="49",
    ))
    db.commit()
    db.close()

    payload = {
        "traded_id": "TID-DUP",       # v10: 原字段名
        "order_id": "OID-IDEM",
        "remark": "10000020",
        "stock_code": "600030.SH",
        "traded_price": 12.5, "traded_volume": 10, "traded_amount": 125.0,  # v10: 原字段名
    }

    db = SessionLocal()
    handle_push(db, "trd_cfm", payload, ts="x")
    db.commit()
    db.close()

    db = SessionLocal()
    handle_push(db, "trd_cfm", payload, ts="x")
    db.commit()
    assert db.query(Trade).filter_by(trade_id="TID-DUP", order_no="10000020", trd_date="20260614").count() == 1
    o = db.query(Order).filter_by(order_no="10000020", trd_date="20260614").first()
    # 累计只算了 1 次
    assert o.traded_volume == 10
    db.close()

def test_trd_cfm_no_remark_skipped_v7():
    """v7: trd_cfm 不带 remark (order_no) → 跳过,不入 Trade 表(避免孤儿 Trade)

    v10: 严格用 broker 原字段名 traded_id / traded_price / traded_volume / traded_amount
    """
    db = SessionLocal()
    db.add(Order(
        trd_date="20260614",
        order_id="OID-FB", user_def="CID-FB", order_no="10000030",
        stock_code="600030.SH", order_type="23", price_type=11, price=12.5, volume=100,
        status="49", traded_volume=0,
    ))
    db.commit()
    db.close()

    db = SessionLocal()
    handle_push(db, "trd_cfm", {
        "traded_id": "TID-FB",        # v10: 原字段名
        "order_id": "OID-FB",
        # 没有 remark (v7: 必须有 order_no 才能落 Trade)
        "stock_code": "600030.SH",
        "traded_price": 12.5, "traded_volume": 20, "traded_amount": 250.0,  # v10: 原字段名
    }, ts="20260614 09:30:00")
    db.commit()
    # v7: Trade 表不入记录（避免孤儿）
    t = db.query(Trade).filter_by(trade_id="TID-FB", order_no="10000030", trd_date="20260614").first()
    assert t is None
    db.close()

def test_trd_cfm_terminal_status_not_overridden():
    """终态(56 部成部撤)被 trd_cfm 累计时不被覆盖

    v10: 严格用 broker 原字段名 traded_id / traded_price / traded_volume / traded_amount
    """
    db = SessionLocal()
    db.add(Order(
        trd_date="20260614",
        order_id="OID-TER", user_def="CID-TER", order_no="10000040",
        stock_code="600030.SH", order_type="23", price_type=11, price=12.5, volume=100,
        status="56",  # 部成部撤终态
        traded_volume=30, traded_amount=375.0,
    ))
    db.commit()
    db.close()

    db = SessionLocal()
    handle_push(db, "trd_cfm", {
        "traded_id": "TID-AFTER-CXL",  # v10: 原字段名
        "order_id": "OID-TER",
        "remark": "10000040",
        "stock_code": "600030.SH",
        "traded_price": 12.5, "traded_volume": 20, "traded_amount": 250.0,  # v10: 原字段名
    }, ts="20260614 10:00:00")
    db.commit()
    o = db.query(Order).filter_by(order_no="10000040", trd_date="20260614").first()
    # 累计还是算了
    assert o.traded_volume == 50
    # 但 status 保持 56(终态保护)
    assert o.status == "56"
    db.close()

# ──── 路由 ────

def test_unknown_func_skipped_silently():
    """未知 func 不报错"""
    db = SessionLocal()
    handle_push(db, "unknown_func", {"foo": "bar"}, ts="x")
    db.commit()  # 不报错即 OK
    db.close()

def test_unknown_func_logs_warning(caplog):
    """未知 func 应记 warning 日志，含 func 名 + 字段上下文（c44ffa4）。

    之前: 静默 return，broker 加新 evt_type 时悄无声息丢失，排查极难。
    之后: 记 warning 日志，便于定位缺失 handler。
    """
    db = SessionLocal()
    with caplog.at_level(logging.WARNING, logger="services.push.handlers"):
        handle_push(db, "bogus_func", {"foo": "bar", "baz": 123}, ts="2026-06-20T10:00:00")
    db.commit()
    db.close()
    # 至少一条 warning 包含 func 名 + 字段 dump
    matched = [r for r in caplog.records
               if r.levelno == logging.WARNING and "bogus_func" in r.getMessage()]
    assert matched, f"expected warning containing 'bogus_func', got: {[r.getMessage() for r in caplog.records]}"
    # 字段上下文也应被记录（便于排查 broker 推了什么）
    assert any("foo" in r.getMessage() for r in matched)

# ──── v9: cancel-row 隔离 ────

def test_ord_cfm_for_original_does_not_touch_cancel_row():
    """v9: broker ord_cfm 推原委托 remark 时,cancel-row 字段完全不被更新。

    背景：DELETE 端点 INSERT 一条 cancel-row（order_flag=1）。
    broker ord_cfm 的 remark 永远是**原委托**的 order_no, 不会回带 cancel-row 的 order_no。
    因此 handle_ord_cfm 用 remark 匹配时永远找不到 cancel-row, cancel-row 字段保持 DELETE 端点写的值。
    """
    db = SessionLocal()
    # 原委托
    db.add(Order(
        trd_date="20260614",
        order_id="OID-ORIG", user_def="CID-ORIG", order_no="10000010",
        stock_code="600030.SH", order_type="23", price_type=11, price=12.5, volume=100,
        status="49", order_flag=0,
    ))
    # cancel-row (DELETE 端点已写入, v11 broker 54=已撤)
    db.add(Order(
        trd_date="20260614",
        order_id=None, user_def="CANCEL:10000010", order_no="10000011",
        stock_code="600030.SH", order_type="23", price_type=11, price=12.5, volume=0,
        status="54", order_flag=1,  # DELETE 端点 RPC 成功已写 54 (v11 broker)
        status_msg="已撤",
    ))
    db.commit()
    db.close()

    # broker 推原委托 ord_cfm (remark=10000010 = 原委托 order_no)
    db = SessionLocal()
    handle_push(db, "ord_cfm", {
        "order_id": "OID-ORIG",
        "remark": "10000010",  # 原委托 order_no, 不是 cancel-row 的 10000011
        "order_status": "51",  # v10: broker 原字段名, broker 51=已报待撤 (非终态)
    }, ts="20260614 09:30:00")
    db.commit()
    db.close()

    # 验证：cancel-row 字段完全没被更新
    db = SessionLocal()
    cancel_row = db.query(Order).filter_by(order_no="10000011", trd_date="20260614").first()
    assert cancel_row is not None, "cancel-row should still exist"
    assert cancel_row.order_flag == 1, f"order_flag should remain 1, got {cancel_row.order_flag}"
    assert cancel_row.status == "54", f"cancel-row status should remain 54 (v11 broker 已撤), got {cancel_row.status}"
    assert cancel_row.status_msg == "已撤", f"status_msg should remain '已撤', got '{cancel_row.status_msg}'"
    assert cancel_row.user_def == "CANCEL:10000010", f"user_def should remain CANCEL:..., got '{cancel_row.user_def}'"
    db.close()

    # 验证：原委托被正常更新
    # broker_status=51 (broker 已报待撤, 在撤单类触发码 51/52/53/54 集合内)
    # + cum_traded=0 → _infer_order_status 规则 3 推断为 54 (broker 已撤)
    # (与 infer_mirror test case 6 一致; 见 server/services/order_status.py)
    db = SessionLocal()
    orig_row = db.query(Order).filter_by(order_no="10000010", trd_date="20260614").first()
    assert orig_row is not None
    assert orig_row.status == "54", f"orig order status inferred to 54 (broker 51 撤单信号 + cum=0), got {orig_row.status}"
    db.close()


# ──── consolidate-position-data-flow: trd_cfm → Position.vol 增量 ────

def test_trd_cfm_updates_position_vol_on_buy():
    """consolidate-position-data-flow §3.2.a: 买单成交 → Position.vol += volume

    初始 Position.vol=100, 成交 30 股买入 → 期望 vol=130
    """
    db = SessionLocal()
    db.add(Order(
        trd_date="20260614",
        order_id="OID-PVB", user_def="CID-PVB", order_no="20000001",
        stock_code="600030.SH", order_type="23", price_type=11, price=12.5, volume=100,
        status="49", traded_volume=0, traded_amount=0,
    ))
    db.add(Position(
        stock_code="600030.SH", stock_name="中证",
        last_vol=100, avl_vol=100, vol=100, cost_price=12.0,
    ))
    db.commit()
    db.close()

    db = SessionLocal()
    handle_push(db, "trd_cfm", {
        "traded_id": "TID-PVB-1",
        "remark": "20000001",
        "stock_code": "600030.SH",
        "order_type": "23",        # 买
        "traded_price": 12.5,
        "traded_volume": 30,
        "traded_amount": 375.0,
    }, ts="20260614 09:31:00")
    db.commit()

    p = db.query(Position).filter_by(stock_code="600030.SH").first()
    assert p is not None
    assert p.vol == 130, f"Position.vol should be 100+30=130, got {p.vol}"
    db.close()

def test_trd_cfm_updates_position_vol_on_sell():
    """consolidate-position-data-flow §3.2.b: 卖单成交 → Position.vol -= volume

    初始 Position.vol=200, 成交 50 股卖出 → 期望 vol=150
    """
    db = SessionLocal()
    db.add(Order(
        trd_date="20260614",
        order_id="OID-PVS", user_def="CID-PVS", order_no="20000002",
        stock_code="600031.SH", order_type="24", price_type=11, price=15.0, volume=80,
        status="49", traded_volume=0, traded_amount=0,
    ))
    db.add(Position(
        stock_code="600031.SH", stock_name="测试",
        last_vol=200, avl_vol=200, vol=200, cost_price=14.0,
    ))
    db.commit()
    db.close()

    db = SessionLocal()
    handle_push(db, "trd_cfm", {
        "traded_id": "TID-PVS-1",
        "remark": "20000002",
        "stock_code": "600031.SH",
        "order_type": "24",        # 卖
        "traded_price": 15.0,
        "traded_volume": 50,
        "traded_amount": 750.0,
    }, ts="20260614 10:00:00")
    db.commit()

    p = db.query(Position).filter_by(stock_code="600031.SH").first()
    assert p is not None
    assert p.vol == 150, f"Position.vol should be 200-50=150, got {p.vol}"
    db.close()

def test_trd_cfm_skips_when_position_not_found(caplog):
    """consolidate-position-data-flow §3.2.c: Position 不存在 → log warning + 跳过

    admin 必须先 day-init reconcile 才能开市交易。未跑 reconcile 时 trd_cfm 落 Trade 行
    但 Position.vol 跳过，不抛错（不能让 push 链路因 Position 缺而中断）。
    """
    db = SessionLocal()
    db.add(Order(
        trd_date="20260614",
        order_id="OID-PNF", user_def="CID-PNF", order_no="20000003",
        stock_code="600032.SH", order_type="23", price_type=11, price=12.5, volume=100,
        status="49", traded_volume=0,
    ))
    # 注意：故意不插 Position 行（模拟 day-init 未跑的场景）
    db.commit()
    db.close()

    db = SessionLocal()
    with caplog.at_level(logging.WARNING):
        handle_push(db, "trd_cfm", {
            "traded_id": "TID-PNF-1",
            "remark": "20000003",
            "stock_code": "600032.SH",
            "order_type": "23",
            "traded_price": 12.5,
            "traded_volume": 30,
            "traded_amount": 375.0,
        }, ts="20260614 09:30:00")
    db.commit()

    # Trade 行正常插入（与 Position 失败解耦）
    t = db.query(Trade).filter_by(trade_id="TID-PNF-1", order_no="20000003").first()
    assert t is not None, "Trade row should still be inserted"

    # Position 仍未创建（我们没有创建，也不会凭空新建）
    p = db.query(Position).filter_by(stock_code="600032.SH").first()
    assert p is None, "Position must NOT be auto-created by trd_cfm"
    db.close()

def test_trd_cfm_does_not_touch_other_position_fields():
    """consolidate-position-data-flow §3.2.d: trd_cfm 只动 vol，其它字段全部不动

    cost_price / avl_vol / today_buy / today_sell / last_vol / stock_name
    全部由 day-init reconcile 负责（DR-2 路径分工）。
    """
    db = SessionLocal()
    db.add(Order(
        trd_date="20260614",
        order_id="OID-PNT", user_def="CID-PNT", order_no="20000004",
        stock_code="600033.SH", order_type="23", price_type=11, price=12.5, volume=100,
        status="49", traded_volume=0,
    ))
    db.add(Position(
        stock_code="600033.SH", stock_name="证券",
        last_vol=100, today_buy=0, today_sell=20,
        avl_vol=80, vol=100, cost_price=11.5,
    ))
    db.commit()
    db.close()

    db = SessionLocal()
    handle_push(db, "trd_cfm", {
        "traded_id": "TID-PNT-1",
        "remark": "20000004",
        "stock_code": "600033.SH",
        "order_type": "23",
        "traded_price": 12.5,
        "traded_volume": 30,
        "traded_amount": 375.0,
    }, ts="20260614 09:31:00")
    db.commit()

    p = db.query(Position).filter_by(stock_code="600033.SH").first()
    assert p is not None
    # 必动
    assert p.vol == 130, f"vol should be 100+30=130, got {p.vol}"
    # 全不动
    assert p.last_vol == 100, f"last_vol should remain 100, got {p.last_vol}"
    assert p.avl_vol == 80, f"avl_vol should remain 80 (T+1, 由 reconcile 负责), got {p.avl_vol}"
    assert p.today_buy == 0, f"today_buy should remain 0 (由 reconcile 负责), got {p.today_buy}"
    assert p.today_sell == 20, f"today_sell should remain 20 (由 reconcile 负责), got {p.today_sell}"
    assert p.cost_price == 11.5, f"cost_price should remain 11.5 (由 reconcile 负责), got {p.cost_price}"
    assert p.stock_name == "证券", f"stock_name should remain, got {p.stock_name}"
    db.close()

def test_trd_cfm_cancel_trade_skips_position_vol():
    """consolidate-position-data-flow §3.2.e + OQ-1 option B: trade_type=1 跳过 Position.vol

    DELETE 端点已对 cancel-trade 做 R1 抹平（cancelled_volume = volume），
    trd_cfm 这条若再 ±vol 会与 R1 抹平语义冲突。
    故 trade_type=1 直接跳过 Position.vol 更新（Position 其他字段当然更不动）。
    """
    db = SessionLocal()
    db.add(Order(
        trd_date="20260614",
        order_id="OID-CTC", user_def="CID-CTC", order_no="20000005",
        stock_code="600034.SH", order_type="23", price_type=11, price=12.5, volume=100,
        status="54",     # broker 已撤 (v11)
        cancelled_volume=80,       # DELETE 端点 R1 抹平后
        order_flag=1,              # cancel-row
        traded_volume=20, traded_amount=250.0,
    ))
    db.add(Position(
        stock_code="600034.SH", stock_name="撤单测试",
        last_vol=100, avl_vol=100, vol=100, cost_price=12.0,
    ))
    db.commit()
    db.close()

    db = SessionLocal()
    handle_push(db, "trd_cfm", {
        "traded_id": "TID-CTC-1",
        "remark": "20000005",
        "stock_code": "600034.SH",
        "order_type": "23",        # broker 仍报 23=买（cancel-trade 实际是 reverse）
        "traded_price": 12.5,
        "traded_volume": 80,       # 抹平的 80 股
        "traded_amount": 1000.0,
        "trade_type": 1,           # 关键: cancel-trade 标记
    }, ts="20260614 09:35:00")
    db.commit()

    # Trade 行正常插入（cancel-trade 也要记录）
    t = db.query(Trade).filter_by(trade_id="TID-CTC-1", order_no="20000005").first()
    assert t is not None
    assert t.trade_type == 1, "Trade.trade_type should be 1"

    # Position.vol 不变（OQ-1 option B: trade_type=1 跳过）
    p = db.query(Position).filter_by(stock_code="600034.SH").first()
    assert p is not None
    assert p.vol == 100, f"Position.vol should remain 100 (cancel-trade skipped), got {p.vol}"
    db.close()
