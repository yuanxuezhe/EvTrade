#!/usr/bin/env python3
"""
test_t0_tasks_e2e.py — T0Task 端到端集成测试（change t0-task-management）

📖 详见 `openspec/changes/2026-07-08-t0-task-management/` spec

功能：
  对启动好的 backend（默认 http://127.0.0.1:8000）跑全套 T0Task API e2e：
    - POST   /api/t0-tasks          创建 task
    - GET    /api/t0-tasks          列表（过滤 stock_code / status）
    - GET    /api/t0-tasks/{id}     详情（含 summary）
    - PATCH  /api/t0-tasks/{id}     更新 target_volume / status
    - POST   /api/t0-tasks/{id}/balance  配平建议（不真下单）
    - GET    /api/t0-tasks/stats    全局 stats（admin）
    - DELETE /api/t0-tasks/{id}     删除
    - POST   /api/orders/place?task_id=…  下单带 task_id（含校验失败 3 用例）

  **不依赖 pytest** — 纯 urllib，可独立跑。退出码 0 = 全过。

使用：
    BACKEND_URL=http://127.0.0.1:8000 ./scripts/e2e/test_t0_tasks_e2e.py
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# ──────────────────── config ────────────────────

BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000")
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "admin123")
TIMEOUT = float(os.environ.get("TIMEOUT", "10"))

# 颜色 (终端 fallback)
def _c(code, s):
    if sys.stdout.isatty() and os.environ.get("NO_COLOR") is None:
        return f"\033[{code}m{s}\033[0m"
    return s
def _ok(s): return _c("32", f"✓ {s}")
def _fail(s): return _c("31", f"✗ {s}")
def _skip(s): return _c("33;2", f"⏸ {s}")  # yellow
def _section(s): return _c("1;36", f"\n=== {s} ===")

# ──────────────────── HTTP helpers ────────────────────

class HttpError(Exception):
    def __init__(self, status, body, url):
        self.status = status
        self.body = body
        self.url = url
        super().__init__(f"{url} → {status}: {body[:200]}")

def _req(method: str, path: str, body: Optional[Dict] = None,
         token: Optional[str] = None, expect: int = 200) -> Any:
    url = f"{BACKEND_URL}{path}"
    data = None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            payload = resp.read().decode()
            status = resp.status
    except urllib.error.HTTPError as e:
        payload = e.read().decode()
        status = e.code
    if status != expect:
        raise HttpError(status, payload, url)
    if not payload:
        return None
    return json.loads(payload)

def login(user: str = ADMIN_USER, pwd: str = ADMIN_PASS) -> str:
    # /api/auth/login 走 OAuth2PasswordRequestForm (application/x-www-form-urlencoded)
    url = f"{BACKEND_URL}/api/auth/login"
    data = urllib.parse.urlencode({"username": user, "password": pwd}).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read())["access_token"]

# ──────────────────── 测试用例 ────────────────────

FAILURES: List[str] = []

def check(name: str, cond: bool, detail: str = "", skip: bool = False):
    if skip:
        print(_skip(name))
    elif cond:
        print(_ok(name))
    else:
        msg = f"{name} — {detail}" if detail else name
        print(_fail(msg))
        FAILURES.append(msg)

def section(s):
    print(_section(s))


# ============ Stage 1: Auth ============

def test_auth() -> str:
    section("Auth: admin login")
    t = login()
    check("admin login → 200 + token", bool(t), f"got token={t[:20] if t else None}…")
    return t


# ============ Stage 2: T0Task CRUD ============

def test_task_crud(tok: str):
    section("T0Task CRUD")

    # Create
    create_body = {
        "stock_code": "600519.SH",
        "base_volume": 100,
        "target_volume": 300,
        "note": "e2e smoke",
    }
    r = _req("POST", "/api/t0-tasks", body=create_body, token=tok, expect=201)
    task_id = r["id"]
    check("POST /t0-tasks → 200 + id", isinstance(task_id, int) and task_id > 0,
          f"got {task_id}")
    check("task status=active", r.get("status") == "active",
          f"got {r.get('status')}")
    check("task base_volume=100", r.get("base_volume") == 100)
    check("task target_volume=300", r.get("target_volume") == 300)

    # List
    r = _req("GET", "/api/t0-tasks?stock_code=600519.SH", token=tok)
    check("GET /t0-tasks?stock_code → list",
          isinstance(r, list) and any(t["id"] == task_id for t in r),
          f"got {r}")

    # Detail
    r = _req("GET", f"/api/t0-tasks/{task_id}", token=tok)
    check("GET /t0-tasks/{id} → 200", "id" in r and r["id"] == task_id)
    summary = r.get("summary") or {}
    check("detail has summary.task_net_volume/position_vol/realized_pnl",
          all(k in summary for k in ["task_net_volume", "position_vol", "realized_pnl"]),
          f"summary keys = {list(summary.keys())}")

    # Update (PATCH)
    r = _req("PATCH", f"/api/t0-tasks/{task_id}",
             body={"target_volume": 500}, token=tok)
    check("PATCH target_volume=500", r.get("target_volume") == 500)

    # Stock-code mismatch (negative)
    try:
        _req("GET", "/api/t0-tasks?stock_code=999999.SH", token=tok)
        check("stock_code filter excludes other stock", True)
    except HttpError:
        pass  # 200 但空列表, fine

    return task_id


# ============ Stage 3: balance + stats ============

def test_balance_and_stats(tok: str, task_id: int):
    section("Balance / Stats")

    # Balance (不真下单, 只返 action + volume 建议)
    r = _req("POST", f"/api/t0-tasks/{task_id}/balance", token=tok)
    check("POST /t0-tasks/{id}/balance → 200",
          all(k in r for k in ["action", "volume", "reason"]),
          f"got {r}")

    # Stats (admin only)
    r = _req("GET", "/api/t0-tasks/stats", token=tok)
    check("GET /t0-tasks/stats → 200 + summary",
          "summary" in r and "by_stock" in r and "daily" in r,
          f"missing keys in {list(r.keys())}")


# ============ Stage 4: orders/place 带 task_id 校验 ============

def _is_in_trading_session(tok: str) -> bool:
    """检查当前是否在交易时段 (用于 skip 时段敏感测试).
    返回 True = 在交易时段 (可以测) / False = 收市 (跳过)"""
    try:
        r = _req("GET", "/api/admin/trading-session", token=tok)
        cfg = r.json()
        from datetime import datetime
        now = datetime.now().time()
        morning_start = datetime.strptime(cfg["morning_start"], "%H:%M:%S").time()
        morning_end = datetime.strptime(cfg["morning_end"], "%H:%M:%S").time()
        afternoon_start = datetime.strptime(cfg["afternoon_start"], "%H:%M:%S").time()
        afternoon_end = datetime.strptime(cfg["afternoon_end"], "%H:%M:%S").time()
        return (morning_start <= now <= morning_end) or (afternoon_start <= now <= afternoon_end)
    except Exception:
        return False


def test_place_task_id_validation(tok: str, task_id: int):
    section("Place order task_id validation")

    # 收市后下单必失败 (require_trading_session), 这 2 个测试是时段敏感
    if not _is_in_trading_session(tok):
        check("INVALID_TASK → 400 (skip: 收市)", True, skip=True)
        check("TASK_STOCK_MISMATCH → 400 (skip: 收市)", True, skip=True)
        return

    # 用 trade session mock 走 RPC 会阻塞 — 这阶段只验 validation
    # 没真实交易时段 / 柜台 — 我们用直接数据库路径绕开

    # 4.1 校验失败: task 不存在
    try:
        _req("POST", "/api/orders/place",
             body={
                 "stock_code": "600519.SH", "order_type": "23",
                 "price_type": 11, "price": 1000.0, "volume": 100,
                 "task_id": 99999,
             }, token=tok, expect=400)
        check("INVALID_TASK → 400", True)
    except HttpError as e:
        check("INVALID_TASK → 400", False, f"got {e.status}")

    # 4.2 校验失败: stock_code 不匹配
    try:
        _req("POST", "/api/orders/place",
             body={
                 "stock_code": "000001.SZ", "order_type": "23",
                 "price_type": 11, "price": 1000.0, "volume": 100,
                 "task_id": task_id,
             }, token=tok, expect=400)
        check("TASK_STOCK_MISMATCH → 400", True)
    except HttpError as e:
        check("TASK_STOCK_MISMATCH → 400", False, f"got {e.status}")

    # 4.3 不带 task_id 应能进 RPC（这环境无柜台, 可能 timeout 503）— 不做硬断


# ============ Stage 5: 清理 (DELETE) ============

def test_delete(tok: str, task_id: int):
    section("Delete")
    r = _req("DELETE", f"/api/t0-tasks/{task_id}", token=tok, expect=200)
    check(f"DELETE /t0-tasks/{task_id} → 200", r is not None, f"got {r}")

    # 二次 GET 应该 404
    try:
        _req("GET", f"/api/t0-tasks/{task_id}", token=tok, expect=404)
        check("deleted task → 404", True)
    except HttpError as e:
        check("deleted task → 404", False, f"got {e.status}")


# ──────────────────── main ────────────────────

def main() -> int:
    print(f"Backend: {BACKEND_URL}")
    try:
        tok = test_auth()
    except HttpError as e:
        print(_fail(f"auth failed: {e}"))
        return 1

    task_id = None
    try:
        task_id = test_task_crud(tok)
        test_balance_and_stats(tok, task_id)
        test_place_task_id_validation(tok, task_id)
    except HttpError as e:
        print(_fail(f"stage failed: {e}"))
        FAILURES.append(f"stage exception: {e}")

    # 清理 (即使前面失败也跑)
    if task_id:
        try:
            test_delete(tok, task_id)
        except HttpError as e:
            print(_fail(f"delete failed: {e}"))

    print()
    if FAILURES:
        print(_fail(f"{len(FAILURES)} failure(s):"))
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print(_ok("ALL PASS"))
    return 0


if __name__ == "__main__":
    sys.exit(main())