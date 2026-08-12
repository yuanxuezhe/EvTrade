"""
server/auth/session.py — token session cache 跨 worker 共享 (MySQL ENGINE=MEMORY)

REQ-AUTH-IDLE-001 (2026-07-31):
  - token session cache 维护 active token 列表 + last_seen_at (idle 计时)
  - idle > IDLE_TIMEOUT_SECONDS (10min) 视为过期 → 401
  - 后端重启 → cache 清空 → 所有 token 失效 (用户期望)

v128.2 (2026-08-12) 跨 worker 修复:
  - v127.2 加 --workers 4 → 4 个独立 Python 进程, 各自的模块级 dict
  - 登录写 worker A, 鉴权读 worker B → 401 "登录已过期"
  - 解决: cache 落 MySQL `token_sessions` 表 (ENGINE=MEMORY)
    * server-wide: 所有 worker 进程共享同一份
    * 重启即清空: MySQL 重启 / backend 重启都失效 (用户期望语义保留)
    * PK = SHA256(token) hex (64 字符): 不存原文 token (DB dump 不泄露凭证)

调用者 (签名不变, 内部实现从 dict → SQL):
  - server/auth/deps.py::get_current_user: is_valid + touch
  - server/api/auth.py::login: register_token
  - server/api/auth.py::logout: revoke
  - server/api/auth.py::grant: register_token (admin 永久 token)
  - server/ws/endpoint.py: touch (WS ping 续期 HTTP session)
"""
import asyncio
import hashlib
import logging
import time
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import text as _text

from server.infra.db import engine as _db_engine
from server.tables import TokenSessions

_log = logging.getLogger("auth.session")

# 10 分钟无交互 → token 失效
IDLE_TIMEOUT_SECONDS = 600
# 后台 sweep 间隔 (秒)
SWEEP_INTERVAL_SECONDS = 60


# ──────────────────────── 内部 helper ────────────────────────

def _hash_token(token: str) -> str:
    """token → SHA256 hex (64 字符), 作 PK + 比较. 不存原文 token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now() -> datetime:
    """统一时钟源 (datetime 版, 便于存 DATETIME 列). tests 可 monkeypatch time.time."""
    return datetime.fromtimestamp(time.time())


# ──────────────────────── 对外 API (签名同 v118, 实现从 dict 改 SQL) ────────────────────────

def register_token(token: str, user_id: int, role: str) -> None:
    """登录成功时把新 token 写入 cache. INSERT IGNORE: 同 token 重复注册幂等."""
    th = _hash_token(token)
    now = _now()
    # INSERT IGNORE: 同 token_hash 已存在 → 跳过 (幂等, 避免 IntegrityError)
    sql = _text("""
        INSERT IGNORE INTO token_sessions
            (token_hash, user_id, role, created_at, last_seen_at)
        VALUES (:th, :uid, :role, :now, :now)
    """)
    with _db_engine.begin() as conn:
        conn.execute(sql, {"th": th, "uid": user_id, "role": role, "now": now})
    _log.info(f"register_token user_id={user_id} role={role!r}")


def touch(token: str) -> None:
    """每个鉴权 HTTP 请求都调, 重置 last_seen_at. 不存在的 token 静默 no-op."""
    th = _hash_token(token)
    sql = _text("UPDATE token_sessions SET last_seen_at = :now WHERE token_hash = :th")
    with _db_engine.begin() as conn:
        conn.execute(sql, {"th": th, "now": _now()})


def is_valid(token: str) -> bool:
    """检查 token 是否在 cache 且 idle 未超 10 分钟."""
    th = _hash_token(token)
    sql = _text(
        "SELECT last_seen_at FROM token_sessions WHERE token_hash = :th LIMIT 1"
    )
    with _db_engine.connect() as conn:
        row = conn.execute(sql, {"th": th}).first()
    if row is None or row[0] is None:
        return False
    last_seen_at: datetime = row[0]
    idle = (_now() - last_seen_at).total_seconds()
    return idle <= IDLE_TIMEOUT_SECONDS


def revoke(token: str) -> None:
    """主动撤销 token (logout). 不存在的 token 静默 no-op."""
    th = _hash_token(token)
    sql = _text("DELETE FROM token_sessions WHERE token_hash = :th")
    with _db_engine.begin() as conn:
        conn.execute(sql, {"th": th})


def sweep_expired() -> int:
    """清掉所有 idle > IDLE_TIMEOUT_SECONDS 的条目, 返回清理条数."""
    cutoff = _now() - timedelta(seconds=IDLE_TIMEOUT_SECONDS)
    sql = _text("DELETE FROM token_sessions WHERE last_seen_at < :cutoff")
    with _db_engine.begin() as conn:
        result = conn.execute(sql, {"cutoff": cutoff})
        n = result.rowcount
    if n:
        _log.info(f"swept {n} expired tokens")
    return n or 0


def stats() -> dict:
    """debug 用: 返回当前 cache 状态."""
    sql = _text("SELECT COUNT(*) FROM token_sessions")
    with _db_engine.connect() as conn:
        size = conn.execute(sql).scalar() or 0
    return {
        "size": int(size),
        "idle_timeout_seconds": IDLE_TIMEOUT_SECONDS,
    }


def _clear_all_for_test() -> None:
    """测试 helper: 清空 token_sessions 表. 生产代码不应调用."""
    sql = _text("DELETE FROM token_sessions")
    with _db_engine.begin() as conn:
        conn.execute(sql)


async def sweep_loop(interval_seconds: int = SWEEP_INTERVAL_SECONDS) -> None:
    """后台 sweep 协程, 在 FastAPI lifespan 启动, shutdown cancel.
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