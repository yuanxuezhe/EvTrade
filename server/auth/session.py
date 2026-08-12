"""
server/auth/session.py — token session cache 跨线程共享 (进程内 dict + RLock)

REQ-AUTH-IDLE-001 (2026-07-31):
  - token session cache 维护 active token 列表 + last_seen_at (idle 计时)
  - idle > IDLE_TIMEOUT_SECONDS (10min) 视为过期 → 401
  - 后端重启 → cache 清空 → 所有 token 失效 (用户期望)

v128.4 (2026-08-12) 单进程回归:
  - v127.2 加 --workers 4 → 4 进程独立 dict → 跨进程 401 "登录已过期"
  - v128.2 改 SQL (ENGINE=MEMORY) 跨 worker 共享 — 引入额外依赖与抖动
  - 改回单进程部署 (删 --workers 4) → 进程内 dict 可跨线程共享 (RLock 保护)
  - dict 写微秒级, 比 SQL 简单太多, 无 ENGINE=MEMORY 锁竞争
  - 重启清空语义保留 (进程内 dict, 重启即失)

调用者 (签名不变, 内部实现 dict + RLock):
  - server/auth/deps.py::get_current_user: is_valid + touch
  - server/api/auth.py::login: register_token
  - server/api/auth.py::logout: revoke
  - server/api/auth.py::grant: register_token (admin 永久 token)
  - server/ws/endpoint.py: touch (WS ping 续期 HTTP session)
"""
import asyncio
import hashlib
import logging
import threading
import time
from typing import Optional

_log = logging.getLogger("auth.session")

# 10 分钟无交互 → token 失效
IDLE_TIMEOUT_SECONDS = 600
# 后台 sweep 间隔 (秒)
SWEEP_INTERVAL_SECONDS = 60


# ──────────────────────── 内部 helper ────────────────────────

def _hash_token(token: str) -> str:
    """token → SHA256 hex (64 字符), 作 dict key + 比较. 不存原文 token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ──────────────────────── 共享 in-memory cache ────────────────────────

# 进程内 dict, 跨线程共享 (RLock 保护). 重启即清空 (用户期望语义).
# PK = SHA256(token) hex (64 字符) — 不存原文, dict dump 不泄露凭证.
_TOKEN_CACHE: dict = {}
_TOKEN_LOCK = threading.RLock()  # RLock 允许重入 (e.g. is_valid 内 touch)


# ──────────────────────── 对外 API (签名同 v118, 实现从 SQL 改 dict) ────────────────────────

def register_token(token: str, user_id: int, role: str) -> None:
    """登录成功时把新 token 写入 cache. 同 token 重复注册幂等 (覆盖 last_seen_at)."""
    th = _hash_token(token)
    with _TOKEN_LOCK:
        _TOKEN_CACHE[th] = {
            "user_id": user_id,
            "role": role,
            "created_at": time.time(),
            "last_seen_at": time.time(),
        }
    _log.info(f"register_token user_id={user_id} role={role!r}")


def touch(token: str) -> None:
    """每个鉴权 HTTP 请求都调, 重置 last_seen_at. 不存在的 token 静默 no-op."""
    th = _hash_token(token)
    with _TOKEN_LOCK:
        entry = _TOKEN_CACHE.get(th)
        if entry is not None:
            entry["last_seen_at"] = time.time()


def is_valid(token: str) -> bool:
    """检查 token 是否在 cache 且 idle 未超 10 分钟."""
    th = _hash_token(token)
    with _TOKEN_LOCK:
        entry = _TOKEN_CACHE.get(th)
        if entry is None:
            return False
        return (time.time() - entry["last_seen_at"]) <= IDLE_TIMEOUT_SECONDS


def revoke(token: str) -> None:
    """主动撤销 token (logout). 不存在的 token 静默 no-op."""
    th = _hash_token(token)
    with _TOKEN_LOCK:
        _TOKEN_CACHE.pop(th, None)


def sweep_expired() -> int:
    """清掉所有 idle > IDLE_TIMEOUT_SECONDS 的条目, 返回清理条数."""
    cutoff = time.time() - IDLE_TIMEOUT_SECONDS
    removed = 0
    with _TOKEN_LOCK:
        expired_keys = [
            th for th, e in _TOKEN_CACHE.items()
            if e["last_seen_at"] < cutoff
        ]
        for th in expired_keys:
            del _TOKEN_CACHE[th]
            removed += 1
    if removed:
        _log.info(f"swept {removed} expired tokens")
    return removed


def stats() -> dict:
    """debug 用: 返回当前 cache 状态."""
    with _TOKEN_LOCK:
        size = len(_TOKEN_CACHE)
    return {
        "size": size,
        "idle_timeout_seconds": IDLE_TIMEOUT_SECONDS,
    }


def _clear_all_for_test() -> None:
    """测试 helper: 清空 cache. 生产代码不应调用."""
    with _TOKEN_LOCK:
        _TOKEN_CACHE.clear()


async def sweep_loop(interval_seconds: int = SWEEP_INTERVAL_SECONDS) -> None:
    """后台 sweep 协程, 在 FastAPI lifespan 启动, shutdown cancel.
    协程内部用 try/except 兜住 CancelledError, 保证优雅退出.
    """
    _log.info(f"sweep_loop started, interval={interval_seconds}s, idle_timeout={IDLE_TIMEOUT_SECONDS}s")
    try:
        while True:
            await asyncio.sleep(interval_seconds)
            try:
                sweep_expired()
            except Exception as e:
                _log.error(f"sweep_expired error: {e}")
    except asyncio.CancelledError:
        _log.info("sweep_loop cancelled, exiting")
        raise