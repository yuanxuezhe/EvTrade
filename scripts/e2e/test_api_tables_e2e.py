#!/usr/bin/env python3
"""Smoke-test the tables-migrated stocks, trades, and asset GET APIs."""
import json
import os
import urllib.parse
import urllib.request


BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000")
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "admin123")
TIMEOUT = float(os.environ.get("TIMEOUT", "10"))


def login() -> str:
    # v2026-08-24: 走 hermesagent 授信, 永久 JWT, 不再走 OAuth2 login (admin 密码外泄风险).
    import sys as _sys
    _sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    from evtrade_grant import auth_header  # noqa: E402
    return auth_header(role="admin")["Authorization"].split(" ", 1)[1]


def check_get(path: str, token: str) -> None:
    request = urllib.request.Request(
        f"{BACKEND_URL}{path}",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        body = json.loads(response.read().decode())
        assert response.status == 200, f"{path}: HTTP {response.status}"
        assert body.get("code") == 0, f"{path}: {body}"
        assert isinstance(body.get("list"), list), f"{path}: list missing"
        print(f"PASS {path}: HTTP 200, rows={len(body['list'])}")


def main() -> None:
    token = login()
    for path in ("/api/stocks", "/api/trades", "/api/asset"):
        check_get(path, token)


if __name__ == "__main__":
    main()