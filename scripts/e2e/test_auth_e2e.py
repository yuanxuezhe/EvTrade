#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_auth_e2e.py — Auth API 端到端集成测试

📖 详见 server/MIGRATION_GUIDE.md 与 server/api/auth.py

功能：对启动好的 backend（默认 http://127.0.0.1:8000）跑全套 Auth API e2e：
  - POST   /api/auth/login           200 + JWT
  - POST   /api/auth/login           401 (错误密码)
  - POST   /api/auth/login           401 (用户名不存在)
  - GET    /api/auth/me              200 + 当前用户信息
  - GET    /api/auth/me              401 (无 token)
  - PATCH  /api/auth/me              200 + 持久化 email / full_name
  - POST   /api/auth/change-password 200 + 密码轮换 (旧→新→旧)
  - POST   /api/auth/logout          200

**不依赖 pytest** — 纯 urllib，可独立跑。退出码 0 = 全过。

使用：
    BACKEND_URL=http://127.0.0.1:8000 ./scripts/e2e/test_auth_e2e.py
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
    """OAuth2PasswordRequestForm login, 返回 access_token (raw str, 不抛异常).

    失败抛 HttpError.
    """
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
    """包装 _login_form, 期望 200."""
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


# ============ Stage 1: /login ============

def test_login_success() -> str:
    section("POST /api/auth/login — happy path")
    tok = login()
    check("login → 200 + non-empty token", bool(tok) and len(tok) > 20,
          f"got token={tok[:20] if tok else None}…")
    return tok


def test_login_wrong_password():
    section("POST /api/auth/login — wrong password")
    try:
        _login_form(ADMIN_USER, "WRONG_PASSWORD_xyz")
        check("wrong password → 401", False, "got 200 instead")
    except HttpError as e:
        check("wrong password → 401", e.status == 401, f"got {e.status}")


def test_login_unknown_user():
    section("POST /api/auth/login — unknown user")
    try:
        _login_form("no_such_user_e2e_9999", "x")
        check("unknown user → 401", False, "got 200 instead")
    except HttpError as e:
        check("unknown user → 401", e.status == 401, f"got {e.status}")


# ============ Stage 2: /me ============

def test_me_success(tok: str):
    section("GET /api/auth/me — with token")
    me = _req("GET", "/api/auth/me", token=tok)
    check("/me → 200 + id", isinstance(me.get("id"), int) and me["id"] > 0,
          f"got id={me.get('id')}")
    check("/me username=admin", me.get("username") == ADMIN_USER,
          f"got {me.get('username')}")
    check("/me role=admin", me.get("role") == "admin", f"got {me.get('role')}")
    check("/me is_active=true", me.get("is_active") is True,
          f"got {me.get('is_active')}")


def test_me_no_token():
    section("GET /api/auth/me — no token")
    try:
        _req("GET", "/api/auth/me", expect=401)
        check("/me no token → 401", True)
    except HttpError as e:
        check("/me no token → 401", False, f"got {e.status}")


# ============ Stage 3: PATCH /me ============

def test_patch_me(tok: str):
    section("PATCH /api/auth/me — update profile")
    marker = f"v81-mig-{int(time.time())}"
    new_email = f"{marker}@example.com"
    new_full_name = f"Mig Tester {marker}"

    # Update email + full_name
    upd = _req("PATCH", "/api/auth/me",
               body={"email": new_email, "full_name": new_full_name},
               token=tok)
    check("PATCH /me → 200", isinstance(upd, dict))
    check("PATCH persists email", upd.get("email") == new_email,
          f"got {upd.get('email')!r}")
    check("PATCH persists full_name", upd.get("full_name") == new_full_name,
          f"got {upd.get('full_name')!r}")

    # Verify GET /me reflects the update (持久化校验)
    me2 = _req("GET", "/api/auth/me", token=tok)
    check("GET /me after PATCH → email 持久化",
          me2.get("email") == new_email, f"got {me2.get('email')!r}")
    check("GET /me after PATCH → full_name 持久化",
          me2.get("full_name") == new_full_name, f"got {me2.get('full_name')!r}")

    # Empty string handling: full_name="" → None (与原 ORM 行为一致)
    upd_empty = _req("PATCH", "/api/auth/me",
                     body={"full_name": ""}, token=tok)
    check("PATCH full_name='' → None (空串转 None)",
          upd_empty.get("full_name") is None,
          f"got {upd_empty.get('full_name')!r}")

    # 还原 (不影响后续 / change-password 测试)
    #   UpdateProfileRequest.email 是 str=Nonedefault, Pydantic v2 拒收显式 null,
    #   改用空串 → server 端 strip() or None 同样落到 None.
    _req("PATCH", "/api/auth/me",
         body={"email": "", "full_name": ""}, token=tok)


# ============ Stage 4: /change-password ============

def test_change_password(tok: str):
    section("POST /api/auth/change-password — password rotation")
    new_pwd = "v81_test_pwd_2026"
    # 1) 改成新密码
    r = _req("POST", "/api/auth/change-password",
             body={"new_password": new_pwd}, token=tok)
    check("change-password → 200 + success", r.get("success") is True,
          f"got {r}")
    # 2) 新密码能登录
    new_tok = login(ADMIN_USER, new_pwd)
    check("新密码 login → 200 + token", bool(new_tok) and len(new_tok) > 20)
    # 3) 旧密码现在 401
    try:
        _login_form(ADMIN_USER, ADMIN_PASS)
        check("旧密码 不能再登录 (已被覆盖) → 401", False, "got 200")
    except HttpError as e:
        check("旧密码 不能再登录 (已被覆盖) → 401", e.status == 401,
              f"got {e.status}")
    # 4) 还原 (用新密码登录 + 再改回)
    r2 = _req("POST", "/api/auth/change-password",
              body={"new_password": ADMIN_PASS}, token=new_tok)
    check("change-password 还原原密码 → 200", r2.get("success") is True,
          f"got {r2}")
    # 5) 原密码能再登录
    restored_tok = login(ADMIN_USER, ADMIN_PASS)
    check("原密码再次可登录 → 200", bool(restored_tok))


# ============ Stage 5: /logout ============

def test_logout(tok: str):
    section("POST /api/auth/logout")
    r = _req("POST", "/api/auth/logout", token=tok)
    check("logout → 200 + success", r.get("success") is True,
          f"got {r}")


# ──────────────────── main ────────────────────

def main() -> int:
    print(f"Backend: {BACKEND_URL}")
    tok = None
    try:
        # Stage 1: login
        tok = test_login_success()
        test_login_wrong_password()
        test_login_unknown_user()
        # Stage 2: me
        if tok:
            test_me_success(tok)
        test_me_no_token()
        # Stage 3: patch me
        if tok:
            test_patch_me(tok)
        # Stage 4: change-password (may invalidate tok → 末尾还原)
        if tok:
            test_change_password(tok)
        # Stage 5: logout
        if tok:
            test_logout(tok)
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