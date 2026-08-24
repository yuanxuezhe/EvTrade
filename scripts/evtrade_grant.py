#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
evtrade_grant.py — AI 助手 / 外部脚本调 EvTrade REST API 的"授信 token + HTTP 客户端"工具

⚠️ AI 助手入门口号:
    bash scripts/evtrade_ai.sh get /api/positions     ← AI agent 一行调用
    bash scripts/evtrade_ai.sh role=trader get /api/orders
    from scripts.evtrade_grant import auth_header, get  ← Python 库模式

**严禁**: curl /api/auth/login, curl /api/auth/grant 拼 token, web_extract 拉 127.0.0.1,
execute_code 跑 subprocess 调接口 (2026-08-24 实测 20+ 步浪费).

Usage:
    # 单次调用 (默认 admin)
    python3 scripts/evtrade_grant.py get /api/stocks
    python3 scripts/evtrade_grant.py post /api/auth/heartbeat
    python3 scripts/evtrade_grant.py post /api/orders/cancel '{"order_no":"..."}'

    # 多角色 (env 切换, 互不串)
    EVTRADE_GRANT_ROLE=trader python3 scripts/evtrade_grant.py get /api/orders

    # 库模式 (Python import)
    from scripts.evtrade_grant import auth_header, get, post, grant
    h = auth_header()                     # admin 默认
    h = auth_header(role="trader")        # 显式指定
    r = get("/api/stocks")                # -> (status, body_dict)

设计目标:
    1. 用固定 token "hermesagent" 调 POST /api/auth/grant 拿永久 JWT (exp 2099)
       — 见 openspec/specs/auth/spec.md REQ-AUTH-013 + 知识库/后端服务/用户鉴权/认证与JWT.md §6
    2. token 按角色分文件缓存到 ~/.cache/evtrade/grant_token_<role>.json (0o600),
       admin/trader/viewer? 不授信 viewer, 跨进程复用 (省一次 HTTP)
    3. grant 端点硬编码 admin id bug 已在 server/api/auth.py 修 — 动态查 users 表
    4. 所有受保护接口 (除登录/grant 本身) 都要带 Authorization: Bearer <token>
    5. 401 时**自动重新 grant** 一次重试 (应对后端重启 — session cache 进程内, 重启全失效)
    6. v2026-08-24: grant 支持 admin/trader 两角色 (viewer 不授信, 防止脚本误调只读账号)

约束:
    - 仅标准库 (urllib + json + pathlib) — 不依赖 requests, 任何 venv 都能跑
    - BASE_URL 默认 http://127.0.0.1:8000, 环境变量 EVTRADE_BASE_URL 可覆盖
    - HERMES_AGENT_TOKEN 固定 "hermesagent" — 与 server/auth/security.py:41 常量同源
    - EVTRADE_ALLOW_GRANT_TOKEN 必须 = "1" (server/.env 已配)
    - 默认角色 = admin; 切 trader 用 EVTRADE_GRANT_ROLE=trader 或 grant(role=...)
"""

import json
import os
import sys
import time
from pathlib import Path
from urllib import error as urlerr
from urllib import request as urlreq

BASE_URL = os.environ.get("EVTRADE_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
HERMES_AGENT_TOKEN = "hermesagent"  # 与 server/auth/security.py:41 HERMES_AGENT_TOKEN 同源
DEFAULT_ROLE = os.environ.get("EVTRADE_GRANT_ROLE", "admin")  # admin / trader; viewer 不授信
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "evtrade"
DEFAULT_TIMEOUT = 30  # 订单类 RPC 同步, 30s 保险; 用户可传 timeout= 覆盖
VALID_ROLES = ("admin", "trader")  # grant 白名单; viewer 拒绝


def _log(level: str, msg: str) -> None:
    sys.stderr.write(f"[{level}] {msg}\n")
    sys.stderr.flush()


def _cache_file_for_role(role: str) -> Path:
    """按角色分文件缓存: admin/trader 不同 token 不能互串."""
    return CACHE_DIR / f"grant_token_{role}.json"


def _read_cache(role: str = None) -> dict | None:
    """读本地缓存的 grant token. 不存在/损坏/角色错返回 None."""
    role = role or DEFAULT_ROLE
    f = _cache_file_for_role(role)
    if not f.exists():
        return None
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        # sanity: 必须有 access_token + expires_at > now + role 一致
        if not isinstance(data, dict):
            return None
        if "access_token" not in data or "expires_at" not in data:
            return None
        if data.get("role") != role:  # 缓存串角色了, 拒用
            return None
        if data["expires_at"] <= time.time() + 60:  # 留 60s 余量
            return None
        return data
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def _write_cache(data: dict, role: str = None) -> None:
    role = role or data.get("role") or DEFAULT_ROLE
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # 落盘前 0o600, token 等价密码
    f = _cache_file_for_role(role)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps({**data, "role": role}, ensure_ascii=False), encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(f)


def _http(method: str, path: str, body=None, headers=None, timeout=DEFAULT_TIMEOUT):
    """薄 urllib 封装. 返回 (status, dict_body_or_text). 业务异常由调用方判定."""
    url = f"{BASE_URL}{path}" if not path.startswith("http") else path
    data = None
    final_headers = dict(headers or {})
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        final_headers.setdefault("Content-Type", "application/json")
    req = urlreq.Request(url, data=data, headers=final_headers, method=method)
    try:
        with urlreq.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            try:
                return r.status, json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return r.status, {"_raw": raw.decode("utf-8", errors="replace")}
    except urlerr.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return e.code, {"_raw": raw.decode("utf-8", errors="replace")}
    except (urlerr.URLError, TimeoutError, OSError) as e:
        return 0, {"_error": str(e)}


def _grant(fresh: bool = False, role: str = None) -> dict:
    """调 /api/auth/grant 拿永久 JWT. fresh=True 跳过读 cache. role=admin/trader."""
    role = role or DEFAULT_ROLE
    if role not in VALID_ROLES:
        raise ValueError(f"role must be one of {VALID_ROLES}, got {role!r}")
    cached = None if fresh else _read_cache(role)
    if cached:
        return cached
    _log("INFO", f"POST {BASE_URL}/api/auth/grant role={role} (fresh={fresh})")
    status, body = _http("POST", "/api/auth/grant",
                          body={"token": HERMES_AGENT_TOKEN, "role": role})
    if status != 200 or "access_token" not in body:
        raise RuntimeError(
            f"grant failed: status={status} body={json.dumps(body, ensure_ascii=False)[:300]}\n"
            f"  check server/.env EVTRADE_ALLOW_GRANT_TOKEN=1 + backend up at {BASE_URL}"
        )
    token = body["access_token"]
    expires_in = int(body.get("expires_in", 946080000))  # 30y default
    cached = {
        "access_token": token,
        "expires_at": time.time() + expires_in,
        "user": body.get("user", {}),
        "granted_at": time.time(),
        "role": role,
    }
    _write_cache(cached, role)
    _log("OK", f"got permanent token, role={role} user={cached['user']}, expires_in={expires_in}s")
    return cached


def auth_header(role: str = None) -> dict:
    """返回可直接合并到 requests/urllib headers 的 dict. 自动缓存 + 失效检测."""
    return {"Authorization": f"Bearer {_grant(role=role)['access_token']}"}


def request(method: str, path: str, body=None, params=None, timeout=DEFAULT_TIMEOUT,
            _retry_on_401=True, role: str = None):
    """统一入口. 带 Bearer + 401 自动重试一次 (grant 重新拿).

    params: dict → URL ?key=val&... (FastAPI Query 风格)
    返回 (status, body_dict)
    """
    if params:
        from urllib.parse import urlencode
        sep = "&" if "?" in path else "?"
        path = f"{path}{sep}{urlencode(params)}"
    h = auth_header(role=role)
    status, body_out = _http(method, path, body=body, headers=h, timeout=timeout)
    if status == 401 and _retry_on_401:
        _log("WARN", f"401 on {method} {path} role={role or DEFAULT_ROLE}, retrying with fresh grant")
        _grant(fresh=True, role=role)
        h = auth_header(role=role)
        status, body_out = _http(method, path, body=body, headers=h, timeout=timeout)
    return status, body_out


def get(path: str, params=None, timeout=DEFAULT_TIMEOUT, role: str = None):
    return request("GET", path, params=params, timeout=timeout, role=role)


def post(path: str, body=None, timeout=DEFAULT_TIMEOUT, role: str = None):
    return request("POST", path, body=body, timeout=timeout, role=role)


def put(path: str, body=None, timeout=DEFAULT_TIMEOUT, role: str = None):
    return request("PUT", path, body=body, timeout=timeout, role=role)


def patch(path: str, body=None, timeout=DEFAULT_TIMEOUT, role: str = None):
    return request("PATCH", path, body=body, timeout=timeout, role=role)


def delete(path: str, timeout=DEFAULT_TIMEOUT, role: str = None):
    return request("DELETE", path, timeout=timeout, role=role)


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def _cli_help() -> None:
    print(__doc__)
    print("CLI examples:")
    print("  evtrade_grant.py get /api/auth/me")
    print("  evtrade_grant.py get /api/stocks")
    print("  evtrade_grant.py post /api/auth/heartbeat")
    print("  evtrade_grant.py post /api/orders/cancel '{\"order_no\":\"...\"}'")
    print("  evtrade_grant.py role=trader get /api/orders")
    print("  evtrade_grant.py fresh                # 清当前角色缓存")
    print("  evtrade_grant.py fresh all            # 清所有角色缓存")


def _clear_cache(role: str) -> int:
    f = _cache_file_for_role(role)
    if f.exists():
        f.unlink()
        _log("OK", f"cache cleared: {f}")
        return 0
    _log("INFO", f"no cache file at {f}")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] in ("-h", "--help", "help"):
        _cli_help()
        return 0

    cmd = argv[1]
    if cmd == "fresh":
        if len(argv) >= 3 and argv[2] == "all":
            for r in VALID_ROLES:
                _clear_cache(r)
        else:
            _clear_cache(DEFAULT_ROLE)
        return 0

    if cmd == "auth":
        # 调试用: 打印当前 token 前缀 + 缓存位置
        c = _grant()
        print(f"USER={c['user']}")
        print(f"ROLE={c['role']}")
        print(f"TOKEN={c['access_token']}")
        print(f"CACHE={_cache_file_for_role(c['role'])}")
        print(f"EXPIRES_AT={time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(c['expires_at']))}")
        return 0

    # 支持 CLI 内联 role 切换: evtrade_grant.py role=trader get /api/orders
    cli_role = None
    if cmd.startswith("role="):
        if len(argv) < 3:
            _log("ERR", "role=... needs a command")
            return 2
        cli_role = cmd.split("=", 1)[1]
        if cli_role not in VALID_ROLES:
            _log("ERR", f"role must be one of {VALID_ROLES}, got {cli_role!r}")
            return 2
        cmd = argv[2]
        argv = [argv[0], cmd] + argv[3:]

    if cmd not in ("get", "post", "put", "patch", "delete"):
        _log("ERR", f"unknown command: {cmd}")
        _cli_help()
        return 2

    if len(argv) < 3:
        _log("ERR", f"{cmd} needs a path")
        return 2

    path = argv[2]
    body = None
    if len(argv) >= 4 and argv[3]:
        try:
            body = json.loads(argv[3])
        except json.JSONDecodeError as e:
            _log("ERR", f"body 不是合法 JSON: {e}")
            return 2

    status, body_out = request(cmd.upper(), path, body=body, role=cli_role)
    print(json.dumps({"status": status, "body": body_out}, ensure_ascii=False, indent=2))
    return 0 if 200 <= status < 300 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))