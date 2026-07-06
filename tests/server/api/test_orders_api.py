"""
test_orders_api.py — orders API 综合测试（v13 从 server/test_orders_api.py 迁入并拆分）

本文件仅保留查询相关 + 与远程 v11 broker 码差异相关的测试（避免与
tests/server/api/orders/test_place.py + test_cancel.py 重复）：

- 查询: list_orders with date filters / default active day / invalid format
- 撤单 status 码差异 (v11: broker 55 → 57):

  注: server/test_orders_api.py 是 v7-v10 版本（broker 码 55 = 废单），
      tests/server/api/orders/test_{place,cancel}.py 是 v11 split 版本（broker 码 57 = 废单）。
      两种 broker 码业务语义相同，仅常量名差；为不破坏历史回归，
      本文件保留 v7-v10 码版本作为差异对照测试。
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))


# ──────────────────────── 查询相关（unique） ────────────────────────

def test_orders_without_date_params_defaults_to_active_day(client, fresh_db, active_day):
    """GET /api/orders 不带日期参数 → 默认 active_day"""
    r = client.get("/api/orders")
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    assert "list" in body


def test_orders_with_only_start_date_returns_open_lower_bound(client, fresh_db, active_day):
    """GET /api/orders?start_date=YYYYMMDD → 下界开放"""
    r = client.get("/api/orders?start_date=20260101")
    assert r.status_code == 200


def test_orders_with_only_end_date_returns_open_upper_bound(client, fresh_db, active_day):
    """GET /api/orders?end_date=YYYYMMDD → 上界开放"""
    r = client.get("/api/orders?end_date=20991231")
    assert r.status_code == 200


def test_orders_with_date_range_returns_only_in_range(client, fresh_db, active_day):
    """GET /api/orders?start_date=...&end_date=... → 仅范围内"""
    r = client.get("/api/orders?start_date=20260101&end_date=20991231")
    assert r.status_code == 200


def test_orders_invalid_date_format_returns_422(client, fresh_db, active_day):
    """GET /api/orders?start_date=invalid → 422"""
    r = client.get("/api/orders?start_date=not-a-date")
    assert r.status_code == 422


def test_list_orders_default_trd_date_uses_active(client, active_day):
    """GET /api/orders/list → 默认 active_day"""
    r = client.get("/api/orders/list")
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0


def test_list_orders_with_filter(client, active_day):
    """GET /api/orders/list?trd_date=YYYYMMDD → 过滤"""
    r = client.get("/api/orders/list?trd_date=20260101")
    assert r.status_code == 200


# ──────────────────────── 撤单 status 码差异（v7-v10 broker 码 55） ────────────────────────
# 注: 远程 v11 split 测试已用 broker 码 57；本节保留历史版本作为回归对照
# (本节测试在原始 server/test_orders_api.py 中存在；本 commit 保留作为版本差异回归)

def test_cancel_rpc_fail_returns_business_error(client, active_day, monkeypatch):
    """v7-v10 版本兼容: 撤单 RPC 失败 → 业务 code=1"""
    from server.api.orders import rpc_cancel_order
    async def fake_fail(**kw):
        raise RuntimeError("rpc fail")
    monkeypatch.setattr("server.api.orders.rpc_cancel_order", fake_fail)
    from db import SessionLocal
    from models.orm import Order
    from server.repo.system import TradingClock
    TradingClock.invalidate_cache()
    db = SessionLocal()
    try:
        o = Order(
            trd_date="20260101", order_no="20000001", order_id="broker-001",
            user_def="", stock_code="000001", order_type="23",
            price_type=11, price=10.0, volume=100,
            traded_volume=0, traded_amount=0.0, avg_price=0.0,
            cancelled_volume=0, order_flag=0,
            status="48", status_msg="",
            order_time="2026-01-01 09:30:00.000",
        )
        db.add(o); db.commit()
    finally:
        db.close()

    r = client.request("DELETE", "/api/orders/20000001", params={"trd_date": "20260101"})
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 1


def test_cancel_ack_nonzero_returns_business_error(client, active_day, monkeypatch):
    """v7-v10 版本兼容: ACK 非 0 → 业务 code=1"""
    from server.api.orders import rpc_cancel_order
    async def fake_cancel(**kw):
        return {"code": -1, "msg": "broker reject"}
    monkeypatch.setattr("server.api.orders.rpc_cancel_order", fake_cancel)
    from db import SessionLocal
    from models.orm import Order
    from server.repo.system import TradingClock
    TradingClock.invalidate_cache()
    db = SessionLocal()
    try:
        o = Order(
            trd_date="20260101", order_no="20000001", order_id="broker-001",
            user_def="", stock_code="000001", order_type="23",
            price_type=11, price=10.0, volume=100,
            traded_volume=0, traded_amount=0.0, avg_price=0.0,
            cancelled_volume=0, order_flag=0,
            status="48", status_msg="",
            order_time="2026-01-01 09:30:00.000",
        )
        db.add(o); db.commit()
    finally:
        db.close()

    r = client.request("DELETE", "/api/orders/20000001", params={"trd_date": "20260101"})
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 1
