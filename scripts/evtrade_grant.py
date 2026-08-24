#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
evtrade_grant.py — AI 助手 / 外部脚本调 EvTrade REST API 的"授信 token + HTTP 客户端"工具

Usage:
    # 单次调用
    uv run python scripts/evtrade_grant.py get /api/stocks
    uv run python scripts/evtrade_grant.py get /api/auth/me
    uv run python scripts/evtrade_grant.py post /api/orders/cancel '{"order_no":"..."}'
    uv run python scripts/evtrade_grant.py post /api/auth/heartbeat

    # 库模式 (Python import)
    from scripts.evtrade_grant import auth_header, get, post, client
    h = auth_header()                   # -> {"Authorization": "Bearer eyJ..."}
    r = get("/api/stocks")              # -> urllib Response (json() helper)
    r = post("/api/orders/cancel", {"order_no": "..."})

设计目标:
    1. 用固定 token "hermesagent" 调 POST /api/auth/grant 拿永久 JWT (exp 2099)
       — 见 openspec/specs/auth/spec.md REQ-AUTH-013 + 知识库/后端服务/用户鉴权/认证与JWT.md §6
    2. token 缓存到 ~/.cache/evtrade_grant.json, 跨进程复用 (省一次 HTTP)
    3. grant 端点硬编码 admin id bug 已在 server/api/auth.py 修 — 动态查 users 表
    4. 所有受保护接口 (除登录/grant 本身) 都要带 Authorization: Bearer <token>
    5. 401 时**自动重新 grant** 一次重试 (应对后端重启 — session cache 进程内, 重启全失效)

约束:
    - 仅标准库 (urllib + json + pathlib) — 不依赖 requests, 任何 venv 都能跑
    - BASE_URL 默认 http://127.0.0.1:8000, 环境变量 EVTRADE_BASE_URL 可覆盖
    - HERMES_AGENT_TOKEN 固定 "hermesagent" — 与 server/auth/security.py:41 常量同源
    - EVTRADE_ALLOW_GRANT_TOKEN 必须 = "1" (server/.env 已配)
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
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "evtrade"
CACHE_FILE = CACHE_DIR / "grant_token.json"
DEFAULT_TIMEOUT = 30  # 订单类 RPC 同步, 30s 保险; 用户可传 timeout= 覆盖


def _log(level: str, msg: str) -> None:
    sys.stderr.write(f"[{level}] {msg}\n")
    sys.stderr.flush()


def _read_cache() -> dict | None:
    """读本地缓存的 grant token. 不存在/损坏返回 None."""
    if not CACHE_FILE.exists():
        return None
    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        # sanity: 必须有 access_token + expires_at > now
        if not isinstance(data, dict):
            return None
        if "access_token" not in data or "expires_at" not in data:
            return None
        if data["expires_at"] <= time.time() + 60:  # 留 60s 余量
            return None
        return data
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def _write_cache(data: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # 落盘前 0o600, token 等价密码
    tmp = CACHE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(CACHE_FILE)


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


def _grant(fresh: bool = False) -> dict:
    """调 /api/auth/grant 拿永久 JWT. fresh=True 跳过读 cache."""
    cached = None if fresh else _read_cache()
    if cached:
        return cached
    _log("INFO", f"POST {BASE_URL}/api/auth/grant (fresh={fresh})")
    status, body = _http("POST", "/api/auth/grant", body={"token": HERMES_AGENT_TOKEN})
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
    }
    _write_cache(cached)
    _log("OK", f"got permanent token, user={cached['user']}, expires_in={expires_in}s")
    return cached


def auth_header() -> dict:
    """返回可直接合并到 requests/urllib headers 的 dict. 自动缓存 + 失效检测."""
    return {"Authorization": f"Bearer {_grant()['access_token']}"}


def request(method: str, path: str, body=None, params=None, timeout=DEFAULT_TIMEOUT,
            _retry_on_401=True):
    """统一入口. 带 Bearer + 401 自动重试一次 (grant 重新拿).

    params: dict → URL ?key=val&... (FastAPI Query 风格)
    返回 (status, body_dict)
    """
    if params:
        from urllib.parse import urlencode
        sep = "&" if "?" in path else "?"
        path = f"{path}{sep}{urlencode(params)}"
    h = auth_header()
    status, body = _http(method, path, body=body, headers=h, timeout=timeout)
    if status == 401 and _retry_on_401:
        _log("WARN", f"401 on {method} {path}, retrying with fresh grant")
        _grant(fresh=True)
        h = auth_header()
        status, body = _http(method, path, body=body, headers=h, timeout=timeout)
    return status, body


def get(path: str, params=None, timeout=DEFAULT_TIMEOUT):
    return request("GET", path, params=params, timeout=timeout)


def post(path: str, body=None, timeout=DEFAULT_TIMEOUT):
    return request("POST", path, body=body, timeout=timeout)


def put(path: str, body=None, timeout=DEFAULT_TIMEOUT):
    return request("PUT", path, body=body, timeout=timeout)


def patch(path: str, body=None, timeout=DEFAULT_TIMEOUT):
    return request("PATCH", path, body=body, timeout=timeout)


def delete(path: str, timeout=DEFAULT_TIMEOUT):
    return request("DELETE", path, timeout=timeout)


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
    print("  evtrade_grant.py fresh                    # 清缓存, 下次强制重新 grant")


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] in ("-h", "--help", "help"):
        _cli_help()
        return 0

    cmd = argv[1]
    if cmd == "fresh":
        if CACHE_FILE.exists():
            CACHE_FILE.unlink()
            _log("OK", f"cache cleared: {CACHE_FILE}")
        else:
            _log("INFO", f"no cache file at {CACHE_FILE}")
        return 0

    if cmd == "auth":
        # 调试用: 打印当前 token 前缀 + 缓存位置
        c = _grant()
        print(f"USER={c['user']}")
        print(f"TOKEN={c['access_token']}")
        print(f"CACHE={CACHE_FILE}")
        print(f"EXPIRES_AT={time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(c['expires_at']))}")
        return 0

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

    status, body_out = request(cmd.upper(), path, body=body)
    print(json.dumps({"status": status, "body": body_out}, ensure_ascii=False, indent=2))
    return 0 if 200 <= status < 300 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))