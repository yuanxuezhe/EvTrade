#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_users_e2e.py — Users API 端到端集成测试

📖 详见 server/MIGRATION_GUIDE.md 与 server/api/users.py

功能：对启动好的 backend（默认 http://127.0.0.1:8000）跑全套 Users API e2e：
  - GET    /api/users            200 + 列表 (含 admin)
  - POST   /api/users            201 + 创建 → 409 重名
  - POST   /api/users/{id}/reset-password 200 + 密码轮换 (旧→新→旧)
  - PATCH  /api/users/{id}       200 + role/email/full_name/is_active 更新
  - DELETE /api/users/{id}       200 + 删除 (最后管理员守卫)
  - GET    /api/users?keyword=&role= 关键词 + 角色过滤

**不依赖 pytest** — 纯 urllib，可独立跑。退出码 0 = 全过。

使用：
    BACKEND_URL=http://127.0.0.1:8000 ./scripts/e2e/test_users_e2e.py
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

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


def _ok(s):
    return _c("32", f"✓ {s}")


def _fail(s):
    return _c("31", f"✗ {s}")


def _section(s):
    return _c("1;36", f"\n=== {s} ===")


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


def _login_form(user: str, pwd: str) -> str:
    """OAuth2PasswordRequestForm login, 返回 access_token."""
    url = f"{BACKEND_URL}/api/auth/login"
    data = urllib.parse.urlencode({"username": user, "password": pwd}).encode()
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            payload = resp.read().decode()
            status = resp.status
    except urllib.error.HTTPError as e:
        payload = e.read().decode()
        status = e.code
    if status != 200:
        raise HttpError(status, payload, url)
    return json.loads(payload)["access_token"]


def login(user: str = ADMIN_USER, pwd: str = ADMIN_PASS) -> str:
    return _login_form(user, pwd)


# ──────────────────── 测试用例 ────────────────────

FAILURES: List[str] = []


def check(name: str, cond: bool, detail: str = ""):
    if cond:
        print(_ok(name))
    else:
        msg = f"{name} — {detail}" if detail else name
        print(_fail(msg))
        FAILURES.append(msg)


def section(s):
    print(_section(s))


# ============ Stage 1: GET /api/users — list ============

def test_list_users(tok: str):
    section("GET /api/users — list")
    users = _req("GET", "/api/users", token=tok)
    check("GET /api/users → 200 + list",
          isinstance(users, list) and len(users) >= 1,
          f"got {type(users).__name__} len={len(users) if isinstance(users, list) else 'N/A'}")
    # 必须包含 admin
    admin_row = next((u for u in users if u.get("username") == ADMIN_USER), None)
    check("列表包含 admin", admin_row is not None, f"got {[u.get('username') for u in users] if isinstance(users, list) else 'N/A'}")
    if admin_row:
        check("admin role=admin", admin_row.get("role") == "admin", f"got {admin_row.get('role')}")
        check("admin is_active=True", admin_row.get("is_active") is True, f"got {admin_row.get('is_active')}")


def test_list_users_keyword_filter(tok: str):
    section("GET /api/users?keyword=admin — keyword filter")
    users = _req("GET", "/api/users?keyword=admin", token=tok)
    check("keyword=admin → 200 + list", isinstance(users, list) and len(users) >= 1,
          f"got len={len(users) if isinstance(users, list) else 'N/A'}")
    # 至少有一个匹配的 (admin 自身)
    has_match = any("admin" in (u.get("username") or "").lower()
                    or "admin" in (u.get("full_name") or "").lower()
                    or "admin" in (u.get("email") or "").lower()
                    for u in users)
    check("keyword=admin 命中至少一条", has_match,
          f"got {[u.get('username') for u in users]}")


def test_list_users_role_filter(tok: str):
    section("GET /api/users?role=admin — role filter")
    users = _req("GET", "/api/users?role=admin", token=tok)
    check("role=admin → 200 + list", isinstance(users, list) and len(users) >= 1,
          f"got len={len(users) if isinstance(users, list) else 'N/A'}")
    all_admin = all(u.get("role") == "admin" for u in users)
    check("role=admin 全部 role==admin", all_admin,
          f"got roles={[u.get('role') for u in users]}")


def test_list_users_no_auth():
    section("GET /api/users — without token (should be 401)")
    try:
        _req("GET", "/api/users", expect=401)
        check("no token → 401", True)
    except HttpError as e:
        check("no token → 401", False, f"got {e.status}")


# ============ Stage 2: POST /api/users — create ============

def test_create_user(tok: str):
    section("POST /api/users — create new user")
    marker = f"e2eu{int(time.time())}"
    payload = {
        "username": marker,
        "password": "v81_test_pwd_2026",
        "role": "trader",
        "email": f"{marker}@example.com",
        "full_name": f"E2E User {marker}",
        "is_active": True,
    }
    new_user = _req("POST", "/api/users", body=payload, token=tok, expect=201)
    check("POST → 201 + id", isinstance(new_user, dict) and isinstance(new_user.get("id"), int),
          f"got {new_user}")
    check("created username echo", new_user.get("username") == marker,
          f"got {new_user.get('username')}")
    check("created role=trader", new_user.get("role") == "trader",
          f"got {new_user.get('role')}")
    check("created is_active=True", new_user.get("is_active") is True,
          f"got {new_user.get('is_active')}")

    # 重名 → 409
    try:
        _req("POST", "/api/users", body=payload, token=tok, expect=409)
        check("重复 username → 409", True)
    except HttpError as e:
        check("重复 username → 409", False, f"got {e.status}")

    # username 太短 → 400
    try:
        bad = dict(payload)
        bad["username"] = "ab"  # 短于 3
        _req("POST", "/api/users", body=bad, token=tok, expect=400)
        check("username 太短 → 400", True)
    except HttpError as e:
        check("username 太短 → 400", False, f"got {e.status}")

    # role 非法 → 400
    try:
        bad = dict(payload)
        bad["username"] = f"e2ebad{int(time.time())}"
        bad["role"] = "hacker"
        _req("POST", "/api/users", body=bad, token=tok, expect=400)
        check("非法 role → 400", True)
    except HttpError as e:
        check("非法 role → 400", False, f"got {e.status}")

    return new_user["id"]


# ============ Stage 3: PATCH /api/users/{id} — update ============

def test_update_user(tok: str, user_id: int):
    section(f"PATCH /api/users/{user_id} — update fields")
    marker = f"upd{int(time.time())}"
    payload = {
        "email": f"upd{marker}@example.com",
        "full_name": f"Updated {marker}",
    }
    upd = _req("PATCH", f"/api/users/{user_id}", body=payload, token=tok)
    check("PATCH → 200", isinstance(upd, dict), f"got {upd}")
    check("PATCH email 持久化", upd.get("email") == payload["email"],
          f"got {upd.get('email')}")
    check("PATCH full_name 持久化", upd.get("full_name") == payload["full_name"],
          f"got {upd.get('full_name')}")

    # is_active 短关 + 还原: 验证持久化但不残留副作用
    upd2 = _req("PATCH", f"/api/users/{user_id}",
                body={"is_active": False}, token=tok)
    check("PATCH is_active=False 持久化", upd2.get("is_active") is False,
          f"got {upd2.get('is_active')}")
    upd3 = _req("PATCH", f"/api/users/{user_id}",
                body={"is_active": True}, token=tok)
    check("PATCH is_active=True 还原", upd3.get("is_active") is True,
          f"got {upd3.get('is_active')}")
    # 角色保持 trader (不改), 避免触发最后管理员守卫误判


# ============ Stage 4: POST /api/users/{id}/reset-password ============

def test_reset_password(tok: str, user_id: int):
    section(f"POST /api/users/{user_id}/reset-password — admin reset")
    new_pwd = "v81_reset_pwd_2026"
    r = _req("POST", f"/api/users/{user_id}/reset-password",
             body={"new_password": new_pwd}, token=tok)
    check("reset-password → 200 + success", r.get("success") is True, f"got {r}")

    # 验证 reset 真生效: 用被改密码的 username 登录应成功, 旧 admin 不受影响.
    target_username = _username_by_id(tok, user_id)
    new_tok = login(target_username, new_pwd)
    check("新密码 login 该用户 → 200 + token", bool(new_tok) and len(new_tok) > 20,
          f"got token={new_tok[:20] if new_tok else None}…")
    check("reset-password 未影响 admin 账号",
          _req("GET", "/api/auth/me", token=tok).get("username") == ADMIN_USER)
    # 还原 — 把 password 改回去 (test_delete_user 不依赖密码, 但清理)
    _req("POST", f"/api/users/{user_id}/reset-password",
         body={"new_password": "v81_test_pwd_2026"}, token=tok)


def _username_by_id(tok: str, user_id: int) -> str:
    """Helper: 用 admin token 查列表, 找到 user_id 对应 username."""
    users = _req("GET", "/api/users", token=tok)
    for u in users:
        if u.get("id") == user_id:
            return u.get("username")
    raise HttpError(404, f"user_id={user_id} not found", "/api/users")


# ============ Stage 5: DELETE /api/users/{id} ============

def test_delete_user(tok: str, user_id: int):
    section(f"DELETE /api/users/{user_id} — remove user")
    # 先降级到 trader (PATCH role=admin 升级后, 不再是最后管理员守卫状态).
    _req("PATCH", f"/api/users/{user_id}", body={"role": "trader", "is_active": True}, token=tok)
    r = _req("DELETE", f"/api/users/{user_id}", token=tok)
    check("DELETE → 200 + success", r.get("success") is True, f"got {r}")

    # 二次删除 → 404
    try:
        _req("DELETE", f"/api/users/{user_id}", token=tok, expect=404)
        check("DELETE 重复 → 404", True)
    except HttpError as e:
        check("DELETE 重复 → 404", False, f"got {e.status}")


def test_last_admin_guard(tok: str):
    section("PATCH /api/users/{admin_id} — last-admin guard")
    # 找 admin user id
    users = _req("GET", "/api/users?role=admin", token=tok)
    admin_rows = [u for u in users if u.get("username") == ADMIN_USER]
    if not admin_rows:
        check("跳过最后管理员守卫测试 (无 admin)", True)
        return
    admin_id = admin_rows[0]["id"]

    # 尝试把 admin 降级到 trader → 应 400 (最后一个 admin)
    try:
        _req("PATCH", f"/api/users/{admin_id}",
             body={"role": "trader"}, token=tok, expect=400)
        check("最后一个 admin 降级 → 400", True)
    except HttpError as e:
        check("最后一个 admin 降级 → 400", False, f"got {e.status}")

    # 尝试禁用 admin → 应 400
    try:
        _req("PATCH", f"/api/users/{admin_id}",
             body={"is_active": False}, token=tok, expect=400)
        check("最后一个 admin 禁用 → 400", True)
    except HttpError as e:
        check("最后一个 admin 禁用 → 400", False, f"got {e.status}")

    # 兜底: 确保 admin 还是 admin + active=true (万一守卫逻辑回归)
    Users_update_safety = _req("GET", "/api/users", token=tok)
    admin_now = next((u for u in Users_update_safety if u.get("id") == admin_id), None)
    if admin_now and (admin_now.get("role") != "admin" or not admin_now.get("is_active")):
        fix = {}
        if admin_now.get("role") != "admin":
            fix["role"] = "admin"
        if not admin_now.get("is_active"):
            fix["is_active"] = True
        _req("PATCH", f"/api/users/{admin_id}", body=fix, token=tok)
        check("admin 状态兜底还原", True)
    else:
        check("admin 状态未受影响 (守卫正确)", True)


def test_self_protect(tok: str, admin_id: int):
    section("DELETE /api/users/{self} — self-delete guard")
    try:
        _req("DELETE", f"/api/users/{admin_id}", token=tok, expect=400)
        check("自删 admin → 400", True)
    except HttpError as e:
        check("自删 admin → 400", False, f"got {e.status}")


# ──────────────────── main ────────────────────

def main() -> int:
    print(f"Backend: {BACKEND_URL}")
    tok = None
    new_user_id = None
    try:
        # Stage 0: login as admin
        section("Login as admin")
        tok = login()
        check("admin login → token", bool(tok))

        # Stage 1: list
        if tok:
            test_list_users(tok)
            test_list_users_keyword_filter(tok)
            test_list_users_role_filter(tok)
        test_list_users_no_auth()

        # Stage 2: create
        if tok:
            new_user_id = test_create_user(tok)

        # Stage 3: update
        if tok and new_user_id is not None:
            test_update_user(tok, new_user_id)

        # Stage 4: reset-password
        if tok and new_user_id is not None:
            test_reset_password(tok, new_user_id)

        # Stage 5: delete (降级 + 激活后删, 避免触发最后管理员守卫)
        if tok and new_user_id is not None:
            test_delete_user(tok, new_user_id)

        # Stage 6: guards (delete 后跑, 此时 user 已删, admin 是唯一管理员)
        if tok:
            test_last_admin_guard(tok)
            users = _req("GET", "/api/users", token=tok)
            admin_row = next((u for u in users if u.get("username") == ADMIN_USER), None)
            if admin_row:
                test_self_protect(tok, admin_row["id"])
    except HttpError as e:
        print(_fail(f"unhandled exception: {e}"))
        FAILURES.append(f"unhandled: {e}")

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