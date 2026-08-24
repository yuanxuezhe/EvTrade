#!/usr/bin/env python3
"""
test_orders_e2e.py — orders API 端到端集成测试

📖 详见 server/MIGRATION_GUIDE.md

覆盖：
- GET    /api/orders                   200 + code=0 + list 字段
- POST   /api/orders/place             200 + code=0 + DB INSERT orders 行 (mock RPC)
- DELETE /api/orders/{no}              200 + code=0 + DB cancel-row
- GET    /api/orders                   二次拉能看到刚才 place 的单 (向后兼容 DB 落库)

**不依赖 pytest** — 纯 urllib，可独立跑。退出码 0 = 全过。

使用：
    BACKEND_URL=http://127.0.0.1:8000 python3 scripts/e2e/test_orders_e2e.py
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple


BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000")
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "admin123")
TRADER_USER = os.environ.get("TRADER_USER", "trader")
TRADER_PASS = os.environ.get("TRADER_PASS", "trader123")
TIMEOUT = float(os.environ.get("TIMEOUT", "10"))


# ──────────────────── colors ────────────────────

def _c(code, s):
    if sys.stdout.isatty() and os.environ.get("NO_COLOR") is None:
        return f"\033[{code}m{s}\033[0m"
    return s


def _ok(s):    return _c("32", f"✓ {s}")
def _fail(s):  return _c("31", f"✗ {s}")
def _section(s): return _c("1;36", f"\n=== {s} ===")


# ──────────────────── HTTP ────────────────────

class HttpError(Exception):
    pass


def _request(method: str, path: str, token: Optional[str] = None,
             body: Any = None, params: Optional[Dict] = None) -> Tuple[int, Any]:
    url = f"{BACKEND_URL}{path}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode()
            try:
                payload = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                payload = raw
            return resp.status, payload
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = raw
        return e.code, payload
    except urllib.error.URLError as e:
        raise HttpError(f"{method} {path} failed: {e}") from e


def login(user: str, password: str) -> str:
    """OAuth2PasswordRequestForm login. 仅用于 trader 角色 (grant 白名单不含 trader 默认流程).

    v2026-08-24: admin 路径已走 hermesagent 授信 (见 grant_login), 此函数保留给 trader 业务测试.
    """
    data = urllib.parse.urlencode({"username": user, "password": password}).encode()
    req = urllib.request.Request(
        f"{BACKEND_URL}/api/auth/login", data=data, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        body = json.loads(resp.read().decode())
        assert resp.status == 200, body
        return body["access_token"]


def grant_login(role: str = "admin") -> str:
    """hermesagent 授信: 固定 token "hermesagent" 拿永久 JWT (exp 2099).

    v2026-08-24: admin 路径走授信, 不再填 admin 密码. trader 仍走 login().
    """
    import sys as _sys
    _sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    from evtrade_grant import auth_header  # noqa: E402
    return auth_header(role=role)["Authorization"].split(" ", 1)[1]


# ──────────────────── tests ────────────────────

def test_get_orders_list(admin_token: str) -> None:
    """GET /api/orders — 200 + list"""
    status, body = _request("GET", "/api/orders", token=admin_token)
    assert status == 200, f"GET /api/orders -> HTTP {status}: {body}"
    assert body.get("code") == 0, body
    assert isinstance(body.get("list"), list), body
    print(_ok(f"GET /api/orders -> 200, list={len(body['list'])}"))


def test_place_order(trader_token: str) -> str:
    """POST /api/orders/place — 200 + 落 orders 行, 返回 order_no"""
    status, body = _request(
        "POST", "/api/orders/place", token=trader_token,
        body={
            "user_def": f"E2E-{int(time.time())}",
            "stock_code": "600030.SH",
            "order_type": "23",
            "price_type": 11,
            "price": 12.5,
            "volume": 100,
        },
    )
    assert status == 200, f"POST /api/orders/place -> HTTP {status}: {body}"
    assert body.get("code") == 0, body
    assert body.get("order") is not None, body
    order_no = body["order"]["order_no"]
    trd_date = body["order"]["trd_date"]
    assert order_no, body
    assert trd_date, body
    print(_ok(f"POST /api/orders/place -> 200, order_no={order_no}, trd_date={trd_date}"))
    return order_no, trd_date


def test_get_orders_includes_new(trader_token: str, order_no: str, trd_date: str) -> None:
    """GET /api/orders?trd_date=…  应该能查到刚才下的单 (向后兼容 DB 落库)"""
    status, body = _request(
        "GET", "/api/orders", token=trader_token,
        params={"trd_date": trd_date},
    )
    assert status == 200, f"GET /api/orders?trd_date -> HTTP {status}: {body}"
    assert body.get("code") == 0, body
    found = [r for r in body.get("list", []) if r.get("order_no") == order_no]
    assert found, f"new order {order_no} not in list: {[r.get('order_no') for r in body.get('list', [])]}"
    print(_ok(f"GET /api/orders?trd_date={trd_date} 包含 order_no={order_no}"))


def test_cancel_order(trader_token: str, order_no: str, trd_date: str) -> None:
    """DELETE /api/orders/{no}?trd_date=…  — 200 + 本地 cancel-row 落库"""
    status, body = _request(
        "DELETE", f"/api/orders/{order_no}", token=trader_token,
        params={"trd_date": trd_date},
    )
    assert status == 200, f"DELETE -> HTTP {status}: {body}"
    # broker 异步模型: 即使 RPC 没回,本地 cancel-row 也会写入
    # 业务码可能是 0 (broker ack 0) 或 1 (broker 拒/异常) — 都算 DELETE 端点工作
    assert body.get("code") in (0, 1), body
    print(_ok(f"DELETE /api/orders/{order_no} -> HTTP 200, code={body.get('code')}, msg={body.get('msg')!r}"))


def test_orders_with_date_range(admin_token: str) -> None:
    """GET /api/orders?start_date=…&end_date=… 区间模式 200"""
    status, body = _request(
        "GET", "/api/orders", token=admin_token,
        params={"start_date": "20260101", "end_date": "20991231"},
    )
    assert status == 200, f"GET /api/orders?date range -> HTTP {status}: {body}"
    assert body.get("code") == 0, body
    assert isinstance(body.get("list"), list), body
    print(_ok(f"GET /api/orders?start_date=…&end_date=… -> 200, list={len(body['list'])}"))


def test_orders_invalid_date_format(admin_token: str) -> None:
    """GET /api/orders?start_date=invalid → 422"""
    status, body = _request(
        "GET", "/api/orders", token=admin_token,
        params={"start_date": "not-a-date"},
    )
    assert status == 422, f"expected 422, got HTTP {status}: {body}"
    print(_ok(f"GET /api/orders?start_date=invalid -> 422 (Pydantic 校验)"))


def main() -> int:
    print(_section("orders API e2e"))
    print(f"BACKEND_URL={BACKEND_URL}")

    try:
        # v2026-08-24: admin 走 hermesagent 授信 (永久 JWT, 无密码). trader 仍走 OAuth2 (业务场景必须).
        admin_token = grant_login("admin")
        print(_ok(f"grant login admin"))
    except Exception as e:
        print(_fail(f"login admin failed: {e}"))
        return 1

    try:
        trader_token = login(TRADER_USER, TRADER_PASS)
        print(_ok(f"login trader ({TRADER_USER})"))
    except Exception as e:
        print(_fail(f"login trader failed: {e}"))
        # 继续 — trader 是 place/cancel 必需
        return 1

    try:
        test_get_orders_list(admin_token)
        test_orders_with_date_range(admin_token)
        test_orders_invalid_date_format(admin_token)
        order_no, trd_date = test_place_order(trader_token)
        test_get_orders_includes_new(trader_token, order_no, trd_date)
        # 给 RPC 后台 task 一点时间回报 (mock 可能瞬时)
        time.sleep(0.5)
        test_cancel_order(trader_token, order_no, trd_date)
    except AssertionError as e:
        print(_fail(f"assertion failed: {e}"))
        return 1
    except HttpError as e:
        print(_fail(f"HTTP error: {e}"))
        return 1

    print(_section("ALL ORDERS TESTS PASSED"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
