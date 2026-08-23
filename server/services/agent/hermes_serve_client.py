"""
server/services/agent/hermes_serve_client.py — Hermes serve daemon JSON-RPC over WS 客户端

Hermes serve 是 Hermes Agent 的 headless JSON-RPC/WebSocket gateway（默认 127.0.0.1:9119）。
本客户端封装：
- 启动 agent run（POST JSON-RPC method=run.start → 返回 run_id）
- 流式订阅 run 事件（WebSocket → step_start/text/tool_call/tool_result/confirmation_required/step_complete/agent_complete/error）
- 响应高危 tool 的二次确认（POST JSON-RPC method=run.confirm）
- 健康检查（GET /healthz）

协议细节：
- JSON-RPC 2.0 over HTTP POST（控制平面）
- WebSocket 订阅（事件流）—— URL 形如 ws://host:port/ws/runs/{run_id}
- 所有响应必须包含 jsonrpc="2.0" + id

参考：
- openspec/changes/2026-08-23-ai-agent-panel/proposal.md
- ~/.hermes/skills/autonomous-ai-agents/hermes-agent/SKILL.md
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional

import httpx
import websockets
from websockets.exceptions import WebSocketException

log = logging.getLogger(__name__)

HERMES_SERVE_URL = os.environ.get("HERMES_SERVE_URL", "http://127.0.0.1:9119")
HERMES_SERVE_WS_URL = os.environ.get("HERMES_SERVE_WS_URL", "ws://127.0.0.1:9119")
HTTP_TIMEOUT = float(os.environ.get("HERMES_HTTP_TIMEOUT", "30.0"))
WS_TIMEOUT = float(os.environ.get("HERMES_WS_TIMEOUT", "300.0"))


class HermesUnreachableError(Exception):
    """Hermes serve daemon 未起 / 网络不可达"""


class HermesError(Exception):
    """Hermes serve 返回业务错误（非网络错误）"""


@dataclass
class HermesEvent:
    """Hermes serve run 事件（WS 流式返回）"""
    type: str  # step_start | text | tool_call | tool_result | confirmation_required | step_complete | agent_complete | error
    run_id: str = ""
    content: str = ""  # text 内容
    tool_name: str = ""  # tool_call / tool_result 的 tool 名
    tool_call_id: str = ""  # tool_call 的 id（用于 respond_confirmation）
    tool_params: dict[str, Any] = field(default_factory=dict)
    tool_result: Any = None
    error_message: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "HermesEvent":
        return cls(
            type=d.get("type", "unknown"),
            run_id=d.get("run_id", ""),
            content=d.get("content", ""),
            tool_name=d.get("tool_name", ""),
            tool_call_id=d.get("tool_call_id", ""),
            tool_params=d.get("tool_params", {}) or {},
            tool_result=d.get("tool_result"),
            error_message=d.get("error_message", "") or d.get("message", ""),
        )


class HermesServeClient:
    """Hermes serve JSON-RPC over WS 客户端（async context manager）"""

    def __init__(
        self,
        base_url: str = HERMES_SERVE_URL,
        ws_base_url: str = HERMES_SERVE_WS_URL,
        timeout: float = HTTP_TIMEOUT,
    ):
        self.base_url = base_url.rstrip("/")
        self.ws_base_url = ws_base_url.rstrip("/")
        self.timeout = timeout
        self._id_counter = 0

    def _next_id(self) -> int:
        self._id_counter += 1
        return self._id_counter

    async def is_reachable(self) -> bool:
        """GET /healthz → True/False"""
        try:
            async with httpx.AsyncClient(timeout=5.0) as c:
                r = await c.get(f"{self.base_url}/healthz")
                return r.status_code == 200
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            log.debug("Hermes healthz failed: %s", e)
            return False

    async def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """JSON-RPC 2.0 POST 单次调用"""
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
            "params": params,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as c:
                r = await c.post(f"{self.base_url}/rpc", json=payload)
        except httpx.RequestError as e:
            raise HermesUnreachableError(f"hermes serve unreachable: {e}") from e
        if r.status_code >= 400:
            raise HermesError(f"hermes HTTP {r.status_code}: {r.text[:200]}")
        try:
            resp = r.json()
        except json.JSONDecodeError as e:
            raise HermesError(f"hermes non-JSON response: {e}") from e
        if "error" in resp:
            err = resp["error"]
            raise HermesError(f"hermes RPC error: {err.get('message', err)}")
        return resp.get("result", {})

    async def start_run(
        self,
        *,
        session_id: str,
        user_message: str,
        tools: list[dict[str, Any]],
        system_prompt: Optional[str] = None,
    ) -> str:
        """启动 agent run → 返回 run_id.

        Args:
            session_id: 会话 id（前端 WS 连接稳定时同一）
            user_message: 用户自然语言消息
            tools: 可用 tool 列表（从 server.mcp.list_tools() 来）
            system_prompt: 自定义 system prompt（可选；不传走 hermes 默认）
        """
        params: dict[str, Any] = {
            "session_id": session_id,
            "message": user_message,
            "tools": tools,
        }
        if system_prompt:
            params["system_prompt"] = system_prompt
        result = await self._rpc("run.start", params)
        run_id = result.get("run_id", "")
        if not run_id:
            raise HermesError(f"hermes run.start missing run_id: {result}")
        return run_id

    async def respond_confirmation(
        self,
        *,
        run_id: str,
        tool_call_id: str,
        confirmed: bool,
    ) -> None:
        """响应高危 tool 的二次确认 → hermes 继续 run"""
        await self._rpc(
            "run.confirm",
            {
                "run_id": run_id,
                "tool_call_id": tool_call_id,
                "confirmed": confirmed,
            },
        )

    async def subscribe_events(
        self,
        run_id: str,
        *,
        ws_timeout: float = WS_TIMEOUT,
    ) -> AsyncIterator[HermesEvent]:
        """订阅 run 事件流（WebSocket）→ AsyncIterator[HermesEvent].

        Yields:
            HermesEvent 直到 type='agent_complete' 或 'error'

        Raises:
            HermesUnreachableError: WS 连接失败
        """
        ws_url = f"{self.ws_base_url}/ws/runs/{run_id}"
        log.info("hermes WS subscribe: %s", ws_url)
        try:
            async with websockets.connect(
                ws_url,
                open_timeout=10.0,
                close_timeout=5.0,
            ) as ws:
                while True:
                    try:
                        raw = await asyncio.wait_for(
                            ws.recv(), timeout=ws_timeout
                        )
                    except asyncio.TimeoutError:
                        log.warning("hermes WS recv timeout: run_id=%s", run_id)
                        break
                    except WebSocketException as e:
                        log.warning("hermes WS closed: %s", e)
                        break
                    try:
                        d = json.loads(raw)
                    except json.JSONDecodeError:
                        log.warning("hermes WS non-JSON frame: %r", raw[:200])
                        continue
                    evt = HermesEvent.from_dict(d)
                    yield evt
                    if evt.type in ("agent_complete", "error"):
                        break
        except (OSError, websockets.WebSocketException) as e:
            raise HermesUnreachableError(f"hermes WS unreachable: {e}") from e

    async def list_available_tools(self) -> list[dict[str, Any]]:
        """列出 hermes 内置 tool（system tools，与我们注入的 mcp tool 并存）

        Returns:
            list of tool dict {name, description, schema, toolset}
        """
        try:
            result = await self._rpc("tools.list", {})
        except HermesUnreachableError:
            log.warning("hermes serve unreachable for tools.list; return empty")
            return []
        return result.get("tools", [])

    # ─── 便利方法：组合 start_run + subscribe_events ─────────────
    async def run_and_subscribe(
        self,
        *,
        session_id: str,
        user_message: str,
        tools: list[dict[str, Any]],
        system_prompt: Optional[str] = None,
    ) -> tuple[str, AsyncIterator[HermesEvent]]:
        """一步：启动 run → 返回 (run_id, 事件迭代器).

        调用方：
            run_id, iter_ = await client.run_and_subscribe(...)
            async for evt in iter_: ...
        """
        run_id = await self.start_run(
            session_id=session_id,
            user_message=user_message,
            tools=tools,
            system_prompt=system_prompt,
        )
        return run_id, self.subscribe_events(run_id)
