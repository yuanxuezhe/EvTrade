"""
server/auth/session.py — token session cache (in-memory) for idle-timeout invalidation.

REQ-AUTH-IDLE-001 (2026-07-31):
  - token 在后端内存中维护一个 session cache, key=token, value={user_id, role, last_seen_at}
  - 每个 HTTP 鉴权请求都 touch() 该 token, 重置 last_seen_at
  - 若 last_seen_at 距今 > IDLE_TIMEOUT_SECONDS (默认 600s=10min), 视为过期
  - sweep_loop 每 60s 清掉过期条目, 控制内存增长
  - 后端重启 → 内存 dict 清零 → 所有 token 立即失效 (用户期望行为)
  - WS 鉴权走独立 heartbeat 机制, 不复用本 cache

设计要点:
  - 内存 only, 不持久化 (用户要的就是后端重启=全部失效)
  - 纯 stdlib (time/asyncio/logging), 无外部依赖
  - sweep task 在 FastAPI lifespan 启动, shutdown 时 cancel
  - pytest 模式 (PYTEST_CURRENT_TEST) 不启 sweep, 避免阻塞测试

调用者:
  - server/auth/deps.py::get_current_user: is_valid + touch
  - server/api/auth.py::login: register_token
  - server/api/auth.py::logout: revoke
"""
import asyncio
import logging
import time
from typing import Optional

_log = logging.getLogger("auth.session")

# 10 分钟无交互 → token 失效
IDLE_TIMEOUT_SECONDS = 600

# 后台 sweep 间隔 (秒)
SWEEP_INTERVAL_SECONDS = 60

# 模块级缓存: token -> {user_id, role, created_at, last_seen_at}
_TOKEN_CACHE: dict = {}


def register_token(token: str, user_id: int, role: str) -> None:
    """登录成功时把新 token 写入 cache。"""
    now = time.time()
    _TOKEN_CACHE[token] = {
        "user_id": user_id,
        "role": role,
        "created_at": now,
        "last_seen_at": now,
    }
    _log.info(f"register_token user_id={user_id} role={role!r} cache_size={len(_TOKEN_CACHE)}")


def touch(token: str) -> None:
    """每个鉴权 HTTP 请求都调, 重置 last_seen_at。
    若 token 已不在 cache (被 sweep 清掉), 此操作静默 no-op — 下一次 is_valid 会返回 False。
    """
    entry = _TOKEN_CACHE.get(token)
    if entry is not None:
        entry["last_seen_at"] = time.time()


def is_valid(token: str) -> bool:
    """检查 token 是否在 cache 且 idle 未超 10 分钟。"""
    entry = _TOKEN_CACHE.get(token)
    if entry is None:
        return False
    if (time.time() - entry["last_seen_at"]) > IDLE_TIMEOUT_SECONDS:
        return False
    return True


def revoke(token: str) -> None:
    """主动撤销 token (logout)。"""
    if _TOKEN_CACHE.pop(token, None) is not None:
        _log.info(f"revoke token, cache_size={len(_TOKEN_CACHE)}")


def sweep_expired() -> int:
    """清掉所有 idle > IDLE_TIMEOUT_SECONDS 的条目, 返回清理条数。"""
    now = time.time()
    expired = [
        t for t, e in _TOKEN_CACHE.items()
        if (now - e["last_seen_at"]) > IDLE_TIMEOUT_SECONDS
    ]
    for t in expired:
        _TOKEN_CACHE.pop(t, None)
    if expired:
        _log.info(f"swept {len(expired)} expired tokens, cache_size={len(_TOKEN_CACHE)}")
    return len(expired)


def stats() -> dict:
    """debug 用: 返回当前 cache 状态。"""
    return {
        "size": len(_TOKEN_CACHE),
        "idle_timeout_seconds": IDLE_TIMEOUT_SECONDS,
    }


async def sweep_loop(interval_seconds: int = SWEEP_INTERVAL_SECONDS) -> None:
    """后台 sweep 协程, 在 FastAPI lifespan 启动, shutdown cancel。
    协程内部用 try/except 兜住 CancelledError, 保证优雅退出。
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