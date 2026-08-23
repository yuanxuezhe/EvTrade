"""
server/services/agent/agent_confirm.py — pending_confirmations 状态机

REQ-ARCH-008 §二次确认协议：
- FastAPI 拦截高危 tool call（白名单）→ 不调 MCP → 推 WS confirmation_required → 等 Future
- 用户 Vue Modal 确认 → FastAPI 解析 Future → 调 MCP tool（这次真执行）→ 继续 hermes run
- 超时（默认 60s）→ Future cancel + 返回 user_rejected 给 hermes

本模块是状态机的单例（线程/进程内一致）。
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)

DEFAULT_CONFIRM_TIMEOUT = float(__import__("os").environ.get("AGENT_CONFIRM_TIMEOUT", "60"))


class ConfirmTimeoutError(Exception):
    """二次确认超时（用户在 timeout 秒内未响应）"""


@dataclass
class _PendingConfirm:
    run_id: str
    tool_call_id: str
    tool_name: str
    tool_params: dict
    future: asyncio.Future  # asyncio.Future[bool]  True=确认 / False=拒绝
    created_at: float
    timeout: float


class ConfirmRegistry:
    """pending_confirmations 状态机（单例）"""

    def __init__(self, default_timeout: float = DEFAULT_CONFIRM_TIMEOUT):
        self._pending: dict[str, _PendingConfirm] = {}
        self._lock = asyncio.Lock()
        self._default_timeout = default_timeout
        self._cleanup_task: Optional[asyncio.Task] = None

    async def start_cleanup_task(self) -> None:
        """启动后台清理任务（每 5s 扫描超时项）"""
        if self._cleanup_task and not self._cleanup_task.done():
            return
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        log.info("ConfirmRegistry cleanup task started")

    async def stop_cleanup_task(self) -> None:
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

    async def _cleanup_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(5.0)
                await self._cleanup_expired()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.warning("ConfirmRegistry cleanup error: %s", e)

    async def _cleanup_expired(self) -> None:
        now = time.time()
        async with self._lock:
            expired = [
                k for k, p in self._pending.items()
                if now - p.created_at > p.timeout
            ]
        for k in expired:
            log.warning("ConfirmRegistry expired: %s", k)
            await self.respond(k, confirmed=False, reason="timeout")

    async def register(
        self,
        *,
        run_id: str,
        tool_call_id: str,
        tool_name: str,
        tool_params: dict,
        timeout: Optional[float] = None,
    ) -> str:
        """注册一个 pending confirmation → 返回 pending_key.

        Args:
            run_id: hermes run id
            tool_call_id: hermes tool call id
            tool_name: 高危 tool 名
            tool_params: tool 调用参数（用于前端预览）
            timeout: 超时秒数（默认 self._default_timeout）

        Returns:
            pending_key: 用于 respond() 的 key
        """
        pending_key = f"{run_id}:{tool_call_id}"
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        async with self._lock:
            # 若已有同 key，先取消旧 future（避免泄漏）
            if pending_key in self._pending:
                old = self._pending[pending_key]
                if not old.future.done():
                    old.future.cancel()
            self._pending[pending_key] = _PendingConfirm(
                run_id=run_id,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                tool_params=tool_params,
                future=future,
                created_at=time.time(),
                timeout=timeout or self._default_timeout,
            )
        log.info(
            "ConfirmRegistry registered: key=%s tool=%s timeout=%ss",
            pending_key, tool_name, timeout or self._default_timeout,
        )
        return pending_key

    async def await_confirmation(
        self,
        pending_key: str,
    ) -> bool:
        """阻塞等待用户确认 → True / False.

        Raises:
            ConfirmTimeoutError: 超时
            asyncio.CancelledError: Future 被外部 cancel
        """
        async with self._lock:
            p = self._pending.get(pending_key)
        if p is None:
            # 已被清理（超时 / 重复）
            raise ConfirmTimeoutError(f"pending_key {pending_key} already resolved/expired")
        try:
            return await asyncio.wait_for(p.future, timeout=p.timeout + 1)
        except asyncio.TimeoutError as e:
            raise ConfirmTimeoutError(
                f"confirmation timeout after {p.timeout}s for {pending_key}"
            ) from e

    async def respond(
        self,
        pending_key: str,
        *,
        confirmed: bool,
        reason: str = "user",
    ) -> bool:
        """用户响应确认 → 解析 Future.

        Returns:
            True = 已响应，False = 找不到 pending_key（可能已超时清理）
        """
        async with self._lock:
            p = self._pending.pop(pending_key, None)
        if p is None:
            log.warning("ConfirmRegistry respond no-op: %s (already gone)", pending_key)
            return False
        if not p.future.done():
            p.future.set_result(confirmed)
        log.info(
            "ConfirmRegistry responded: key=%s confirmed=%s reason=%s",
            pending_key, confirmed, reason,
        )
        return True

    async def get(self, pending_key: str) -> Optional[dict]:
        async with self._lock:
            p = self._pending.get(pending_key)
        if p is None:
            return None
        return {
            "run_id": p.run_id,
            "tool_call_id": p.tool_call_id,
            "tool_name": p.tool_name,
            "tool_params": p.tool_params,
            "created_at": p.created_at,
            "timeout": p.timeout,
            "age": time.time() - p.created_at,
        }

    async def pending_count(self) -> int:
        async with self._lock:
            return len(self._pending)


# ─── 单例 ─────────────────────────────────────────────────────────
_registry: Optional[ConfirmRegistry] = None


def get_confirm_registry() -> ConfirmRegistry:
    """获取全局单例 ConfirmRegistry"""
    global _registry
    if _registry is None:
        _registry = ConfirmRegistry()
    return _registry
