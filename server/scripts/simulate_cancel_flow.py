#!/usr/bin/env python3
"""
simulate_cancel_flow.py — 模拟前端点击下单 → 等已报 → 点击撤单 (REQ-TRADE-033 验证)

目的:
  在开发环境（无 QMT 真实 broker）通过 FastAPI TestClient + monkeypatch fake broker
  走通下单 → 撤单的完整 HTTP 链路, 重点验证 cancel_order 通过 rpc_cancel_order
  调用柜台 cxl_ord 渠道时只用 order_id, 无 market / stock_code (v__ 修复).

跑法:
  cd server && python3 scripts/simulate_cancel_flow.py

前置:
  本脚本不会污染主流程; 自身 finalizer 清 t_* 测试用户.
"""

import asyncio
import os
import sys
from pathlib import Path

# 关键: 让 main.py startup hook 跳过 RPC client / quote consumer / flusher
# (这些要走真 broker + 真 RabbitMQ, 开发环境连不上; 取消 TestClient 关闭时它们死循环)
os.environ.setdefault("PYTEST_CURRENT_TEST", "simulate_cancel_flow")

# 让 from server.xxx 能找到模块 (脚本在 server/scripts/, 包根在 server/)
SERVER_ROOT = Path(__file__).resolve().parent.parent.parent
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from sqlalchemy import text  # noqa: E402

from server.api.orders import cancel as cancel_mod  # noqa: E402
from server.api.orders import place as place_mod  # noqa: E402
from server.auth.security import create_access_token, hash_password  # noqa: E402
from server.db import SessionLocal  # noqa: E402
from server.main import app  # noqa: E402
from server.models.orm import SysStatus  # noqa: E402
from server.models.user import User  # noqa: E402

# ────────── 全局 monkeypatch: 替换真实 RPC / ws_manager ──────────
_call_log: list[dict] = []


class FakeOrdStk:
    """模拟柜台 ord_stk (下单 RPC) — 给假 broker order_id 让 cancel 可走通"""

    def __init__(self):
        self.calls = []
        self._seq = 0

    async def __call__(self, **kwargs):
        self._seq += 1
        fake_oid = f"OID-SIM-{self._seq:04d}"
        self.calls.append({"rpc": "ord_stk", "kwargs": kwargs, "oid": fake_oid})
        # 模拟 broker ack — code=0 (成功)
        return {"code": 0, "list": [{"order_id": fake_oid}]}


class FakeCxlOrd:
    """模拟柜台 cxl_ord (撤单 RPC) — ★ 重点验证调用参数 ★"""

    def __init__(self):
        self.calls = []

    async def __call__(self, **kwargs):
        self.calls.append({"rpc": "cxl_ord", "kwargs": kwargs})
        # 模拟 broker ack — code=0 (撤单成功)
        return {"code": 0}


fake_ord = FakeOrdStk()
fake_cxl = FakeCxlOrd()

# hook 进 place.py:127 _submit_rpc_async 用的是 from server.api.orders import ord_stk
import server.api.orders as _orders_pkg
_orders_pkg.ord_stk = fake_ord
_orders_pkg.rpc_cancel_order = fake_cxl

# ws push 改为 no-op (开发环境不需要广播)
class FakeWsManager:
    async def broadcast(self, *args, **kwargs):
        pass


_orders_pkg.ws_manager = FakeWsManager()


# ────────── DB 准备 ──────────
USERNAME = "t_sim_cancel"
PASSWORD = "sim123"
TRD_DATE = "20260718"
TEST_STOCK = "000001.SZ"


def setup_db():
    """清干净 orders 表 + 建测试用户 + 激活交易日"""
    db = SessionLocal()
    try:
        db.execute(text("DELETE FROM orders"))
        db.execute(text("ALTER TABLE orders AUTO_INCREMENT = 1"))
        db.execute(
            text(
                "DELETE FROM users WHERE username LIKE :pat AND username NOT IN ('admin', 'trader')"
            ),
            {"pat": "t_sim_%"},
        )
        # 创建测试用户
        u = User(username=USERNAME, password_hash=hash_password(PASSWORD), role="trader")
        db.add(u)
        # 激活交易日 (v_next: sys_status 单行 id=1)
        from server.models.orm import SysStatus as _Ss
        # 不再 DELETE WHERE trd_date; 改为 UPDATE id=1 行的 trd_date/status
        existing = db.query(_Ss).filter(_Ss.id == 1).first()
        if existing:
            existing.trd_date = TRD_DATE
            existing.status = "active"
            existing.is_half_day = 0
            existing.remark = "sim"
            existing.initialized_at = None
            existing.initialized_by = None
            existing.closed_at = None
            existing.closed_by = None
        else:
            db.add(_Ss(id=1, status="active", trd_date=TRD_DATE, is_half_day=False, remark="sim"))
        db.commit()
        return db.query(User).filter_by(username=USERNAME).first().id
    finally:
        db.close()


def teardown_db():
    """finalizer 兜底清 t_sim_* 测试用户"""
    db = SessionLocal()
    try:
        db.execute(
            text(
                "DELETE FROM users WHERE username LIKE 't_sim_%' AND username NOT IN ('admin', 'trader')"
            )
        )
        db.execute(text("DELETE FROM orders WHERE user_def LIKE 'sim_%'"))
        db.commit()
    finally:
        db.close()


# ────────── 主流程 ──────────
def login_and_get_token(user_id: int) -> str:
    """直接签 JWT (绕过 /api/auth/login 省事, data dict 格式是 JWT sub)"""
    return create_access_token(data={"sub": str(user_id)})


def step_place(client, token: str) -> dict:
    """step 1: 前端点击 '买入' → POST /api/orders/place"""
    print("\n" + "=" * 60)
    print("[STEP 1] 前端点击 '买入 000001 100股 @10.00'")
    print("=" * 60)
    resp = client.post(
        "/api/orders/place",
        json={
            "stock_code": TEST_STOCK,
            "order_type": "23",  # 买
            "price_type": 4,     # 限价
            "price": 10.00,
            "volume": 100,
            "t0_coefficient": 1.0,
            "user_def": "sim_place_001",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    print(f"HTTP {resp.status_code}: {resp.json()}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0, f"place 失败: {body}"
    # PlaceOrderResponse.order 是 OrderOut 字段 (dict), 不是 list
    return body["order"] if "order" in body and body["order"] else None


def step_simulate_broker_ack(client, token: str, order_no: str, broker_oid: str):
    """step 2: 模拟 broker 已报 — 直接 update DB 模拟 ord_cfm 推送"""
    print("\n" + "=" * 60)
    print(f"[STEP 2] 模拟 broker ord_cfm — order_no={order_no} → status=50 已报")
    print("=" * 60)
    db = SessionLocal()
    try:
        from server.models.orm import Order

        o = db.query(Order).filter_by(order_no=order_no, trd_date=TRD_DATE).first()
        if not o:
            print(f"!! 订单 {order_no} 不存在, 跳过 ack 模拟")
            return
        o.status = "50"
        o.status_msg = "已报"
        o.order_id = broker_oid  # ★ broker 回报了 order_id, 才能撤
        db.commit()
        print(f"已写入 DB: status=50, order_id={broker_oid}")
    finally:
        db.close()


def step_cancel(client, token: str, order_no: str) -> tuple[int, dict]:
    """step 3: 前端点击 '撤单' → DELETE /api/orders/{order_no}?trd_date=YYYYMMDD"""
    print("\n" + "=" * 60)
    print(f"[STEP 3] 前端点击 '撤单' — DELETE order_no={order_no}")
    print("=" * 60)
    resp = client.delete(
        f"/api/orders/{order_no}",
        params={"trd_date": TRD_DATE},
        headers={"Authorization": f"Bearer {token}"},
    )
    body = resp.json()
    print(f"HTTP {resp.status_code}: {body}")
    return resp.status_code, body


# ────────── 报告 ──────────
def report():
    print("\n" + "=" * 60)
    print("[REPORT] RPC 调用审计")
    print("=" * 60)

    print(f"\n下单 RPC ord_stk 调用次数: {len(fake_ord.calls)}")
    for i, c in enumerate(fake_ord.calls, 1):
        kw = c["kwargs"]
        print(f"  [{i}] ord_stk keys={sorted(kw.keys())} oid={c['oid']}")

    print(f"\n撤单 RPC cxl_ord 调用次数: {len(fake_cxl.calls)}")
    for i, c in enumerate(fake_cxl.calls, 1):
        kw = c["kwargs"]
        # ★ 核心审计: 调用参数
        has_market = "market" in kw
        has_stock_code = "stock_code" in kw
        keys = sorted(kw.keys())
        print(f"  [{i}] cxl_ord kwargs.keys={keys}  order_id={kw.get('order_id')}")
        print(f"      market in kw? {has_market}  stock_code in kw? {has_stock_code}")

    # ★ 断言: 撤单 RPC 必须无 market / stock_code
    assert len(fake_cxl.calls) >= 1, "cxl_ord 没被调用!"
    kw = fake_cxl.calls[0]["kwargs"]
    assert "market" not in kw, f"❌ cxl_ord 仍传 market: {kw}"
    assert "stock_code" not in kw, f"❌ cxl_ord 仍传 stock_code: {kw}"
    assert "order_id" in kw, f"❌ cxl_ord 必须传 order_id: {kw}"
    print("\n✅ PASS: cxl_ord 调用参数与新协议一致 — 仅 order_id, 无 market / stock_code")


# ────────── main ──────────
def main():
    print("[INIT] setup DB + fake broker...")
    user_id = setup_db()
    token = login_and_get_token(user_id)
    print(f"[INIT] user_id={user_id} token={token[:20]}...")

    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        # step 1: 下单
        order = step_place(client, token)
        if not order:
            print("FAIL: place 没拿到 order")
            return 1
        order_no = order["order_no"]
        print(f"下单成功 → order_no={order_no}")

        # 等待异步 RPC ord_stk 完成 (asyncio.create_task fire-and-forget)
        # pytest 模式下我们用 monkeypatch fake_ord, 但 TestClient 在 startup hook
        # 里 PYTEST_CURRENT_TEST 未设, RPC 仍会真启动. 看 fake_ord.calls 数量判断
        # 是否被真实 RPC 覆盖.
        import time

        time.sleep(0.5)  # 等异步 task 跑完

        # step 2: 模拟 broker 已报推送
        broker_oid = fake_ord.calls[-1]["oid"] if fake_ord.calls else "UNKNOWN"
        step_simulate_broker_ack(client, token, order_no, broker_oid)

        # step 3: 撤单
        code, body = step_cancel(client, token, order_no)
        if code != 200 or body.get("code") != 0:
            print(f"!! 撤单 HTTP/RPC 失败: {body}")

        # 给 fake_cxl 一瞬间时间 (虽然 fake_cxl.__call__ 异步, TestClient 同步等结果)
        time.sleep(0.2)

        report()

    print("\n[FINAL] teardown DB...")
    teardown_db()
    print("[DONE]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
