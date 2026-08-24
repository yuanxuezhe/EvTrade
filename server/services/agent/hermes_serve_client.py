"""
server/services/agent/hermes_serve_client.py — Hermes API server /v1/runs REST + SSE 客户端

Hermes API server 是 Hermes gateway 自带的 OpenAI 兼容 HTTP server（默认 127.0.0.1:8642）。
本客户端封装：
- 启动 agent run（POST /v1/runs → 202 + {run_id, status}）
- 流式订阅 run 事件（GET /v1/runs/{run_id}/events → SSE text/event-stream）
- 响应高危 tool 二次确认（POST /v1/runs/{run_id}/approval）
- 中断 run（POST /v1/runs/{run_id}/stop）
- 查 run 状态（GET /v1/runs/{run_id}）
- 健康检查（GET /，响应到达判据）

取代旧版 JSON-RPC over WebSocket（hermes serve :9119）。
旧版 see git log < 2026-08-23。

参考：
- openspec/changes/2026-08-23-upgrade-agent-to-v1-runs/proposal.md
- ~/.hermes/skills/autonomous-ai-agents/hermes-agent/SKILL.md（方案 A：Hermes API server :8642）
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional

import httpx

log = logging.getLogger(__name__)

# 配置（环境变量优先，缺省值兜底）
HERMES_API_BASE_URL = os.environ.get("HERMES_API_BASE_URL", "http://127.0.0.1:8642").rstrip(" /")
# 鉴权 key：HERMES_API_KEY 优先；缺省为 dev 默认值（与 ~/.hermes/.env API_SERVER_KEY 对齐，
# 仅本地开发用，prod 必须从环境变量或 secret manager 注入）
_DEV_DEFAULT_KEY = "evtrade-dev-20260823-do-not-use-in-prod"
HERMES_API_KEY = os.environ.get("HERMES_API_KEY") or _DEV_DEFAULT_KEY
HTTP_TIMEOUT = float(os.environ.get("HERMES_HTTP_TIMEOUT", "30.0"))


class HermesUnreachableError(Exception):
    """Hermes API server 未起 / 网络不可达"""


class HermesError(Exception):
    """Hermes API server 返回业务错误（非网络错误）"""


@dataclass
class HermesEvent:
    """Hermes /v1/runs/{run_id}/events SSE 事件透传。

    字段命名对齐 Hermes 实际事件 payload（见 api_server.py 源码）：
      run.started / message.started / tool.progress / tool.started /
      tool.completed / tool.failed / assistant.completed / run.completed /
      approval.required / approval.responded / error / done

    额外包含 run_id / message_id / session_id 便于路由（前端 Store 用 message_id 关联消息）。
    """

    type: str
    run_id: str = ""
    session_id: str = ""
    message_id: str = ""
    content: str = ""
    tool_name: str = ""
    tool_call_id: str = ""
    tool_args: dict[str, Any] = field(default_factory=dict)
    tool_result: Any = None
    pending_key: str = ""
    error_message: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "HermesEvent":
        # Hermes SSE 事件 payload 用 "type" 字段标识事件名
        event_type = d.get("type") or d.get("event") or "unknown"
        # tool.progress payload 的字段是 message_id + tool_name + delta
        # tool.started/completed/failed 的字段是 message_id + tool_name + preview + args / result / error
        # tool_args 必须 dict[str, Any]；统一从 raw 中取出并断言为 dict
        raw_args = d.get("args")
        args: dict[str, Any] = raw_args if isinstance(raw_args, dict) else {}
        return cls(
            type=event_type,
            run_id=d.get("run_id", "") or "",
            session_id=d.get("session_id", "") or "",
            message_id=d.get("message_id", "") or "",
            content=d.get("content", "") or "",
            tool_name=d.get("tool_name", "") or "",
            tool_call_id=d.get("tool_call_id", "") or d.get("toolCallId", "") or "",
            tool_args=args,
            tool_result=d.get("result"),
            pending_key=d.get("pending_key", "") or "",
            error_message=d.get("message", "") or d.get("error", "") or "",
            raw=d,
        )


class HermesServeClient:
    """Hermes API server /v1/runs REST + SSE 客户端（async）。

    用法：
        async with HermesServeClient() as client:
            run_id = await client.submit_run(input="查一下持仓", session_id="sess-1")
            async for event in client.stream_events(run_id):
                if event.type == "run.completed":
                    break
    """

    def __init__(
        self,
        base_url: str = HERMES_API_BASE_URL,
        api_key: str = HERMES_API_KEY,
        timeout: float = HTTP_TIMEOUT,
    ):
        self.base_url = base_url.rstrip(" /")
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def _sse_headers(self) -> dict[str, str]:
        h = {"Accept": "text/event-stream"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    async def is_reachable(self) -> bool:
        """探测 Hermes API server 是否在跑。

        Hermes API server 对所有未注册 GET 路径返 404 JSON（headless 拦截器统一处理），
        只要 daemon 在跑，HTTP 层就有响应。判定标准：HTTP 请求**能拿到响应**
        （无论 200/404/405）即视为可达；只有连接失败/超时才算不可达。

        不用 `/v1/models`：v0.19.0 该端点需 API key 且未必存在 → 鉴权失败不区分可达性。
        沿用 `2026-08-23-fix-agent-is-reachable-healthz` 判据。
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as c:
                r = await c.get(f"{self.base_url}/")
                # 响应到达 → daemon 在跑。不卡 status_code
                return True
        except asyncio.TimeoutError:
            log.debug("Hermes reachable probe timed out")
            return False
        except httpx.RequestError as e:
            log.debug("Hermes reachable probe failed: %s", e)
            return False

    async def submit_run(
        self,
        *,
        input: str,
        session_id: str,
        instructions: Optional[str] = None,
        conversation_history: Optional[list[dict[str, str]]] = None,
    ) -> str:
        """启动 agent run → 返回 run_id.

        POST /v1/runs body:
          {"input": str|list[msg], "session_id": str?, "instructions": str?,
           "conversation_history": [{role, content}]?, "previous_response_id": str?}

        Returns:
            run_id (形如 "run_<32hex>")

        Raises:
            HermesError: 4xx/5xx + 业务错误
            HermesUnreachableError: 网络错误
        """
        payload: dict[str, Any] = {
            "input": input,
            "session_id": session_id,
        }
        if instructions:
            payload["instructions"] = instructions
        if conversation_history:
            payload["conversation_history"] = conversation_history

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as c:
                r = await c.post(
                    f"{self.base_url}/v1/runs",
                    json=payload,
                    headers=self._headers(),
                )
        except httpx.RequestError as e:
            raise HermesUnreachableError(f"hermes API server unreachable: {e}") from e

        if r.status_code >= 400:
            try:
                err_body = r.json()
                err_msg = err_body.get("error", {}).get("message", r.text[:200])
            except Exception:
                err_msg = r.text[:200]
            raise HermesError(f"hermes /v1/runs HTTP {r.status_code}: {err_msg}")

        try:
            body = r.json()
        except json.JSONDecodeError as e:
            raise HermesError(f"hermes /v1/runs non-JSON response: {e}") from e

        run_id = body.get("run_id", "")
        if not run_id:
            raise HermesError(f"hermes /v1/runs missing run_id: {body}")
        return run_id

    async def stream_events(self, run_id: str) -> AsyncIterator[HermesEvent]:
        """订阅 run 事件流（SSE）。

        GET /v1/runs/{run_id}/events → text/event-stream
          帧格式：`data: {"type": "<event>", ...}\\n\\n`
          心跳：`: keepalive\\n\\n`（每 30s 一帧）
          结束：`: stream closed\\n\\n`（服务端 close）

        Yields:
            HermesEvent 直到 type='done'（流结束标记）或服务端 close

        Raises:
            HermesUnreachableError: 连接失败 / 4xx（run not found 404 / auth 401）
        """
        url = f"{self.base_url}/v1/runs/{run_id}/events"
        log.info("hermes SSE subscribe: %s", url)
        try:
            async with httpx.AsyncClient(timeout=None) as c:
                async with c.stream(
                    "GET",
                    url,
                    headers=self._sse_headers(),
                ) as r:
                    if r.status_code == 404:
                        raise HermesUnreachableError(
                            f"hermes run not found (404): {run_id}"
                        )
                    if r.status_code == 401:
                        raise HermesUnreachableError(
                            "hermes API key invalid (401)"
                        )
                    if r.status_code >= 400:
                        raise HermesUnreachableError(
                            f"hermes SSE HTTP {r.status_code}"
                        )
                    r.raise_for_status()
                    # 逐行解析 SSE
                    # Hermes API server 格式：
                    #   data: {"type": "run.started", ...}\n\n
                    #   : keepalive\n\n  (注释行，跳过)
                    #
                    #   : stream closed\n\n (close marker)
                    buffer = ""
                    async for chunk in r.aiter_text():
                        buffer += chunk
                        # 按 \n\n 分割 SSE 帧
                        while "\n\n" in buffer:
                            frame, buffer = buffer.split("\n\n", 1)
                            frame = frame.strip()
                            if not frame or frame.startswith(":"):
                                # SSE 注释（keepalive 或 stream closed）
                                continue
                            # 提取 data: 行
                            data_lines = []
                            for line in frame.splitlines():
                                line = line.strip()
                                if line.startswith("data:"):
                                    data_lines.append(line[5:].strip())
                            if not data_lines:
                                continue
                            data_str = "\n".join(data_lines)
                            try:
                                payload = json.loads(data_str)
                            except json.JSONDecodeError:
                                log.warning(
                                    "hermes SSE non-JSON frame: %r", data_str[:200]
                                )
                                continue
                            evt = HermesEvent.from_dict(payload)
                            # 注入 run_id（payload 可能不带，前端要）
                            if not evt.run_id:
                                evt.run_id = run_id
                            yield evt
                            if evt.type == "done":
                                # 流结束标记
                                return
        except httpx.RequestError as e:
            raise HermesUnreachableError(f"hermes SSE unreachable: {e}") from e

    async def respond_approval(
        self,
        *,
        run_id: str,
        choice: str,
        resolve_all: bool = False,
    ) -> None:
        """响应高危 tool 的二次确认 → Hermes 继续 run.

        POST /v1/runs/{run_id}/approval body:
          {"choice": "once|session|always|deny", "all": bool}

        choice 别名："approve"/"approved"/"allow" 都映射为 "once"
        """
        aliases = {"approve": "once", "approved": "once", "allow": "once"}
        normalized = aliases.get(choice.lower(), choice.lower())
        payload = {"choice": normalized, "all": resolve_all}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as c:
                r = await c.post(
                    f"{self.base_url}/v1/runs/{run_id}/approval",
                    json=payload,
                    headers=self._headers(),
                )
        except httpx.RequestError as e:
            raise HermesUnreachableError(f"hermes approval unreachable: {e}") from e

        if r.status_code == 409:
            # approval_not_active / approval_not_pending
            raise HermesError(f"hermes approval 409: {r.text[:200]}")
        if r.status_code >= 400:
            raise HermesError(f"hermes approval HTTP {r.status_code}: {r.text[:200]}")

    async def stop_run(self, run_id: str) -> None:
        """中断正在运行的 agent。

        POST /v1/runs/{run_id}/stop → 204 No Content
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as c:
                r = await c.post(
                    f"{self.base_url}/v1/runs/{run_id}/stop",
                    headers=self._headers(),
                )
        except httpx.RequestError as e:
            raise HermesUnreachableError(f"hermes stop unreachable: {e}") from e

        if r.status_code == 404:
            # run 已结束，幂等返回 OK
            return
        if r.status_code >= 400:
            raise HermesError(f"hermes stop HTTP {r.status_code}: {r.text[:200]}")

    async def get_run_status(self, run_id: str) -> dict[str, Any]:
        """查 run 状态（轮询用，SSE 不可用时 fallback）。

        GET /v1/runs/{run_id} → {"run_id", "status", "created_at", "last_event", ...}
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as c:
                r = await c.get(
                    f"{self.base_url}/v1/runs/{run_id}",
                    headers=self._headers(),
                )
        except httpx.RequestError as e:
            raise HermesUnreachableError(f"hermes get_run unreachable: {e}") from e

        if r.status_code == 404:
            raise HermesError(f"hermes run not found: {run_id}")
        if r.status_code >= 400:
            raise HermesError(f"hermes get_run HTTP {r.status_code}: {r.text[:200]}")

        try:
            return r.json()
        except json.JSONDecodeError as e:
            raise HermesError(f"hermes get_run non-JSON: {e}") from e

    async def list_models(self) -> list[str]:
        """列 Hermes API server 已配置的模型。

        GET /v1/models → {"data": [{"id": "...", ...}]}
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as c:
                r = await c.get(
                    f"{self.base_url}/v1/models",
                    headers=self._headers(),
                )
        except httpx.RequestError:
            return []
        if r.status_code >= 400:
            return []
        try:
            body = r.json()
        except json.JSONDecodeError:
            return []
        return [m.get("id", "") for m in body.get("data", []) if m.get("id")]


# ─── 全局默认实例（薄包装，单例复用连接池）──────────────────
_default_client: Optional[HermesServeClient] = None


def get_default_client() -> HermesServeClient:
    """拿默认 client 单例。WS handler 内调用，每次都用同一个，httpx 连接池复用。"""
    global _default_client
    if _default_client is None:
        _default_client = HermesServeClient()
    return _default_client


def reset_default_client() -> None:
    """测试用：重置单例。"""
    global _default_client
    _default_client = None