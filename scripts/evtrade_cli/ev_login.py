#!/usr/bin/env python3
"""
ev_login.py — 拿 admin JWT, 缓存到 ~/.ev_token.json

默认授信 admin (v118+ seed 账号):
    username = admin
    password = admin123
    role = admin (全部权限)

用法:
    python3 ev_login.py                     # 拿 token, 打印到 stdout
    python3 ev_login.py --json              # JSON 输出 {token, user_id, role, expires_at}
    python3 ev_login.py --reset-admin       # 强制重置 admin 密码为 admin123 (如果之前改过)

环境变量:
    EV_BASE_URL  默认 http://127.0.0.1:8000
    EV_USER      默认 admin
    EV_PASS      默认 admin123
"""
import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path

DEFAULT_BASE = os.environ.get("EV_BASE_URL", "http://127.0.0.1:8000")
DEFAULT_USER = os.environ.get("EV_USER", "admin")
DEFAULT_PASS = os.environ.get("EV_PASS", "admin123")
TOKEN_CACHE = Path.home() / ".ev_token.json"


def _post_form(url: str, data: dict, timeout: float = 5.0) -> dict:
    """POST application/x-www-form-urlencoded (FastAPI OAuth2PasswordRequestForm)"""
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _post_json(url: str, data: dict, token: str, timeout: float = 10.0) -> dict:
    """POST application/json 带 Bearer token"""
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        return json.loads(raw) if raw else {}


def login(base: str = DEFAULT_BASE, user: str = DEFAULT_USER, pwd: str = DEFAULT_PASS) -> dict:
    """拿 JWT (v92+: 默认走 /api/auth/grant 永久 token, 失败 fallback login).

    优先尝试 grant 端点 (token=hermesagent, 返回 30 年有效 JWT, 无需密码)
    后端需设 EVTRADE_ALLOW_GRANT_TOKEN=1 才启用.
    """
    # 1) 优先 grant 端点 (固定 token, 永久有效)
    try:
        return _grant(base)
    except Exception as e:
        print(f"[ev] grant 失败 ({e}), fallback login admin...")

    # 2) fallback: 传统 login (admin/admin123)
    url = f"{base}/api/auth/login"
    try:
        resp = _post_form(url, {"username": user, "password": pwd})
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise SystemExit(f"[ev] 登录失败: 用户名或密码错误 (user={user})")
        raise SystemExit(f"[ev] 登录失败: HTTP {e.code} {e.read()[:200].decode(errors='replace')}")
    except Exception as e:
        raise SystemExit(f"[ev] 登录失败 (base={base}): {e}")
    token = resp.get("access_token")
    if not token:
        raise SystemExit(f"[ev] 登录响应缺 access_token: {resp}")
    user_info = resp.get("user", {})
    cached = _make_cached(base, token, user_info, expires_in=resp.get("expires_in", 600))
    TOKEN_CACHE.write_text(json.dumps(cached, indent=2))
    return cached


def _grant(base: str = DEFAULT_BASE) -> dict:
    """调 /api/auth/grant 拿永久 token (固定凭证 hermesagent)"""
    url = f"{base}/api/auth/grant"
    resp = _post_json(url, {"token": "hermesagent"}, token="", timeout=10.0)
    token = resp.get("access_token")
    if not token:
        raise RuntimeError(f"grant response 缺 access_token: {resp}")
    user_info = resp.get("user", {})
    expires_in = resp.get("expires_in", 946080000)  # ~30 年
    cached = _make_cached(base, token, user_info, expires_in=expires_in)
    TOKEN_CACHE.write_text(json.dumps(cached, indent=2))
    return cached


def _make_cached(base, token, user_info, expires_in) -> dict:
    return {
        "token": token,
        "user_id": user_info.get("id"),
        "username": user_info.get("username"),
        "role": user_info.get("role"),
        "expires_in": expires_in,
        "issued_at": int(time.time()),
        "expires_at": int(time.time()) + expires_in,
        "base": base,
    }


def get_token() -> str:
    """从缓存读 token, 过期自动重新 grant (永久 token 路径)

    v92+: 默认是 grant 端点的永久 JWT, session cache 10min idle 被 sweep
    但 grant 每次都生成新 token, 频繁 call 反而更安全 (可追溯每次 session)
    """
    if TOKEN_CACHE.exists():
        try:
            cached = json.loads(TOKEN_CACHE.read_text())
            # 永久 token (30 年): 总不过期, 但 session cache 10min 后失效
            # 策略: 缓存 5min 重新 grant 一次 (避免 session sweep 但又不频繁调)
            issued_at = cached.get("issued_at", 0)
            if time.time() - issued_at < 300:  # 5 min 缓存
                return cached["token"]
        except Exception:
            pass
    return login()["token"]


def reset_admin_password(base: str = DEFAULT_BASE) -> None:
    """强制把 admin 密码设回 admin123 (用 DB 直连, 绕过 login)

    ⚠️ 这是 dev-only 工具, 需要 backend 同机 + .env 配 EVTRADE_DB_URL
    """
    print("[ev] reset admin 密码 (dev only)...")
    try:
        from server.infra.db import engine
        from server.auth.security import hash_password
        with engine.begin() as conn:
            from sqlalchemy import text
            new_hash = hash_password(DEFAULT_PASS)
            conn.execute(
                text("UPDATE users SET password_hash=:h WHERE username='admin'"),
                {"h": new_hash},
            )
        print(f"[ev] admin 密码已重置为 {DEFAULT_PASS}")
    except Exception as e:
        print(f"[ev] 重置失败: {e}")
        print("    (需要 backend 同机 + DB 可达, 或直接 SQL: UPDATE users SET password_hash=... WHERE username='admin')")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="ev_login — 拿 EvTrade admin JWT")
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--user", default=DEFAULT_USER)
    parser.add_argument("--pass", dest="password", default=DEFAULT_PASS)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--reset-admin", action="store_true",
                        help="重置 admin 密码为 admin123 (DB 直连)")
    args = parser.parse_args()

    if args.reset_admin:
        reset_admin_password(args.base)
        return

    cached = login(args.base, args.user, args.password)
    if args.json:
        print(json.dumps(cached, indent=2))
    else:
        print(f"[ev] login OK: user={cached['username']!r} role={cached['role']!r} "
              f"expires_in={cached['expires_in']}s "
              f"(token 缓存: {TOKEN_CACHE})")


if __name__ == "__main__":
    main()