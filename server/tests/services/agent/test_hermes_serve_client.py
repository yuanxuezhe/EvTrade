"""
server/tests/services/agent/test_hermes_serve_client.py

单测覆盖 HermesServeClient 新版（Hermes API server :8642 /v1/runs REST + SSE）。

覆盖接口：
- is_reachable
- submit_run
- stream_events（SSE 解析）
- respond_approval
- stop_run
- get_run_status
- list_models
- HermesEvent.from_dict
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from server.services.agent.hermes_serve_client import (
    HERMES_API_BASE_URL,
    HermesError,
    HermesEvent,
    HermesServeClient,
    HermesUnreachableError,
)

API_BASE = "http://test:8642"
API_KEY = "test-key-123"


def _mock_client():
    """构造一个 patch 后用于 httpx.AsyncClient 的 mock ctx manager."""
    m = MagicMock()
    m.__aenter__ = AsyncMock(return_value=m)
    m.__aexit__ = AsyncMock(return_value=False)
    return m


# ─── 1. HermesEvent.from_dict ─────────────────────────────────
class TestHermesEvent:
    """Hermes SSE 事件 payload → HermesEvent 转换。"""

    def test_run_started(self):
        d = {"type": "run.started", "session_id": "s-1"}
        e = HermesEvent.from_dict(d)
        assert e.type == "run.started"
        assert e.session_id == "s-1"
        assert e.raw == d

    def test_assistant_completed(self):
        d = {"type": "assistant.completed", "message_id": "m-1", "content": "hi"}
        e = HermesEvent.from_dict(d)
        assert e.type == "assistant.completed"
        assert e.message_id == "m-1"
        assert e.content == "hi"

    def test_tool_started_with_args(self):
        d = {"type": "tool.started", "tool_name": "list_positions", "args": {"limit": 10}, "preview": "loading..."}
        e = HermesEvent.from_dict(d)
        assert e.type == "tool.started"
        assert e.tool_name == "list_positions"
        assert e.tool_args == {"limit": 10}

    def test_tool_started_args_none_safe(self):
        """args 字段为 None 或缺失时，tool_args 应为空 dict（不 None）"""
        d = {"type": "tool.started", "tool_name": "x", "args": None}
        e = HermesEvent.from_dict(d)
        assert e.tool_args == {}
        d2 = {"type": "tool.started", "tool_name": "x"}
        e2 = HermesEvent.from_dict(d2)
        assert e2.tool_args == {}

    def test_tool_completed_with_result(self):
        d = {"type": "tool.completed", "tool_name": "get_quote", "result": {"price": 1.23}}
        e = HermesEvent.from_dict(d)
        assert e.tool_result == {"price": 1.23}

    def test_approval_required(self):
        d = {"type": "approval.required", "pending_key": "r1:tc1", "tool_name": "place_order", "args": {"stock_code": "600000.SH"}}
        e = HermesEvent.from_dict(d)
        assert e.pending_key == "r1:tc1"
        assert e.tool_name == "place_order"
        assert e.tool_args == {"stock_code": "600000.SH"}

    def test_error_event(self):
        d = {"type": "error", "message": "boom"}
        e = HermesEvent.from_dict(d)
        assert e.error_message == "boom"

    def test_unknown_type_fallback(self):
        """type 字段缺失时用 "unknown" 兜底（防御性）。"""
        d = {"foo": "bar"}
        e = HermesEvent.from_dict(d)
        assert e.type == "unknown"

    def test_minimal_dict(self):
        """空 dict → 所有字段默认值。"""
        e = HermesEvent.from_dict({})
        assert e.type == "unknown"
        assert e.run_id == ""
        assert e.tool_args == {}


# ─── 2. is_reachable ─────────────────────────────────────────
class TestIsReachable:
    """HTTP 响应到达判据（沿用 healthz 修复）。"""

    @pytest.mark.asyncio
    async def test_404_still_reachable(self):
        client = HermesServeClient(base_url=API_BASE, api_key=API_KEY)
        m = _mock_client()
        m.get = AsyncMock(return_value=MagicMock(status_code=404))
        with patch("httpx.AsyncClient", return_value=m):
            assert await client.is_reachable() is True

    @pytest.mark.asyncio
    async def test_200_also_reachable(self):
        client = HermesServeClient(base_url=API_BASE, api_key=API_KEY)
        m = _mock_client()
        m.get = AsyncMock(return_value=MagicMock(status_code=200))
        with patch("httpx.AsyncClient", return_value=m):
            assert await client.is_reachable() is True

    @pytest.mark.asyncio
    async def test_connect_error_returns_false(self):
        client = HermesServeClient(base_url=API_BASE, api_key=API_KEY)
        with patch("httpx.AsyncClient", side_effect=httpx.ConnectError("refused")):
            assert await client.is_reachable() is False

    @pytest.mark.asyncio
    async def test_timeout_returns_false(self):
        client = HermesServeClient(base_url=API_BASE, api_key=API_KEY)
        with patch("httpx.AsyncClient", side_effect=httpx.TimeoutException("slow")):
            assert await client.is_reachable() is False


# ─── 3. submit_run ───────────────────────────────────────────
class TestSubmitRun:
    """POST /v1/runs → 返回 run_id。"""

    @pytest.mark.asyncio
    async def test_returns_run_id(self):
        client = HermesServeClient(base_url=API_BASE, api_key=API_KEY)
        m = _mock_client()
        m.post = AsyncMock(return_value=MagicMock(
            status_code=202,
            json=lambda: {"run_id": "run_abc123", "status": "started"},
        ))
        with patch("httpx.AsyncClient", return_value=m):
            run_id = await client.submit_run(input="hi", session_id="s1")
        assert run_id == "run_abc123"
        # 验证 Authorization 头 + payload
        call_kwargs = m.post.call_args.kwargs
        assert call_kwargs["json"]["input"] == "hi"
        assert call_kwargs["json"]["session_id"] == "s1"
        assert call_kwargs["headers"]["Authorization"] == f"Bearer {API_KEY}"

    @pytest.mark.asyncio
    async def test_includes_optional_instructions(self):
        client = HermesServeClient(base_url=API_BASE, api_key=API_KEY)
        m = _mock_client()
        m.post = AsyncMock(return_value=MagicMock(
            status_code=202,
            json=lambda: {"run_id": "run_xyz"},
        ))
        with patch("httpx.AsyncClient", return_value=m):
            await client.submit_run(input="hi", session_id="s1", instructions="be brief")
        assert m.post.call_args.kwargs["json"]["instructions"] == "be brief"

    @pytest.mark.asyncio
    async def test_5xx_raises_hermes_error(self):
        client = HermesServeClient(base_url=API_BASE, api_key=API_KEY)
        m = _mock_client()
        m.post = AsyncMock(return_value=MagicMock(
            status_code=500,
            text="internal error",
            json=lambda: {"error": {"message": "internal error"}},
        ))
        with patch("httpx.AsyncClient", return_value=m):
            with pytest.raises(HermesError) as exc:
                await client.submit_run(input="hi", session_id="s1")
        assert "500" in str(exc.value)

    @pytest.mark.asyncio
    async def test_missing_run_id_raises(self):
        client = HermesServeClient(base_url=API_BASE, api_key=API_KEY)
        m = _mock_client()
        m.post = AsyncMock(return_value=MagicMock(
            status_code=202,
            json=lambda: {"status": "started"},  # no run_id
        ))
        with patch("httpx.AsyncClient", return_value=m):
            with pytest.raises(HermesError) as exc:
                await client.submit_run(input="hi", session_id="s1")
        assert "missing run_id" in str(exc.value)

    @pytest.mark.asyncio
    async def test_connect_error_raises_unreachable(self):
        client = HermesServeClient(base_url=API_BASE, api_key=API_KEY)
        with patch("httpx.AsyncClient", side_effect=httpx.ConnectError("refused")):
            with pytest.raises(HermesUnreachableError):
                await client.submit_run(input="hi", session_id="s1")


# ─── 4. stream_events SSE 解析 ─────────────────────────────────
class TestStreamEvents:
    """GET /v1/runs/{id}/events SSE → AsyncIterator[HermesEvent]。"""

    @pytest.mark.asyncio
    async def test_parses_sse_frames(self):
        """SSE 格式：data: {...}\\n\\n 多帧。"""
        client = HermesServeClient(base_url=API_BASE, api_key=API_KEY)

        # 构造 aiter_text 返回多块文本
        chunks = [
            'data: {"type": "run.started", "session_id": "s1"}\n\n',
            'data: {"type": "tool.started", "tool_name": "list_positions", "args": {}}\n\n',
            'data: {"type": "tool.completed", "tool_name": "list_positions", "result": []}\n\n',
            'data: {"type": "done"}\n\n',
        ]

        # 构造 httpx AsyncClient.stream() context manager
        stream_response = MagicMock()
        stream_response.status_code = 200
        stream_response.raise_for_status = MagicMock()

        async def fake_aiter_text():
            for c in chunks:
                yield c

        stream_response.aiter_text = fake_aiter_text

        stream_ctx = MagicMock()
        stream_ctx.__aenter__ = AsyncMock(return_value=stream_response)
        stream_ctx.__aexit__ = AsyncMock(return_value=False)

        # httpx.AsyncClient() 返回的 ctx manager；其 .stream() 也返回 ctx manager
        async_client_mock = MagicMock()
        async_client_mock.__aenter__ = AsyncMock(return_value=async_client_mock)
        async_client_mock.__aexit__ = AsyncMock(return_value=False)
        async_client_mock.stream = MagicMock(return_value=stream_ctx)

        with patch("httpx.AsyncClient", return_value=async_client_mock):
            events = []
            async for evt in client.stream_events("run_abc"):
                events.append(evt)

        assert [e.type for e in events] == [
            "run.started",
            "tool.started",
            "tool.completed",
            "done",
        ]
        assert events[1].tool_name == "list_positions"
        # done 事件之后 stream_events 应退出（不再 yield）

    @pytest.mark.asyncio
    async def test_skips_sse_comments(self):
        """: keepalive 注释行应被跳过（不触发 yield）。"""
        client = HermesServeClient(base_url=API_BASE, api_key=API_KEY)

        chunks = [
            ": keepalive\n\n",
            'data: {"type": "run.started"}\n\n',
            ": keepalive\n\n",
            'data: {"type": "done"}\n\n',
        ]

        stream_response = MagicMock()
        stream_response.status_code = 200
        stream_response.raise_for_status = MagicMock()

        async def fake_aiter_text():
            for c in chunks:
                yield c

        stream_response.aiter_text = fake_aiter_text

        stream_ctx = MagicMock()
        stream_ctx.__aenter__ = AsyncMock(return_value=stream_response)
        stream_ctx.__aexit__ = AsyncMock(return_value=False)

        async_client_mock = MagicMock()
        async_client_mock.__aenter__ = AsyncMock(return_value=async_client_mock)
        async_client_mock.__aexit__ = AsyncMock(return_value=False)
        async_client_mock.stream = MagicMock(return_value=stream_ctx)

        with patch("httpx.AsyncClient", return_value=async_client_mock):
            events = []
            async for evt in client.stream_events("run_x"):
                events.append(evt)

        # : keepalive 不应出现在 events 里
        assert len(events) == 2
        assert events[0].type == "run.started"
        assert events[1].type == "done"

    @pytest.mark.asyncio
    async def test_404_raises_unreachable(self):
        client = HermesServeClient(base_url=API_BASE, api_key=API_KEY)
        stream_response = MagicMock(status_code=404)

        stream_ctx = MagicMock()
        stream_ctx.__aenter__ = AsyncMock(return_value=stream_response)
        stream_ctx.__aexit__ = AsyncMock(return_value=False)

        async_client_mock = MagicMock()
        async_client_mock.__aenter__ = AsyncMock(return_value=async_client_mock)
        async_client_mock.__aexit__ = AsyncMock(return_value=False)
        async_client_mock.stream = MagicMock(return_value=stream_ctx)

        with patch("httpx.AsyncClient", return_value=async_client_mock):
            with pytest.raises(HermesUnreachableError) as exc:
                async for _ in client.stream_events("run_nonexistent"):
                    pass
        assert "not found" in str(exc.value).lower()


# ─── 5. respond_approval ─────────────────────────────────────
class TestRespondApproval:
    """POST /v1/runs/{id}/approval。"""

    @pytest.mark.asyncio
    async def test_once_choice(self):
        client = HermesServeClient(base_url=API_BASE, api_key=API_KEY)
        m = _mock_client()
        m.post = AsyncMock(return_value=MagicMock(status_code=200, text="ok"))
        with patch("httpx.AsyncClient", return_value=m):
            await client.respond_approval(run_id="r1", choice="once")
        body = m.post.call_args.kwargs["json"]
        assert body == {"choice": "once", "all": False}

    @pytest.mark.asyncio
    async def test_approve_alias_maps_to_once(self):
        client = HermesServeClient(base_url=API_BASE, api_key=API_KEY)
        m = _mock_client()
        m.post = AsyncMock(return_value=MagicMock(status_code=200, text="ok"))
        with patch("httpx.AsyncClient", return_value=m):
            await client.respond_approval(run_id="r1", choice="approve")
        assert m.post.call_args.kwargs["json"]["choice"] == "once"

    @pytest.mark.asyncio
    async def test_resolve_all(self):
        client = HermesServeClient(base_url=API_BASE, api_key=API_KEY)
        m = _mock_client()
        m.post = AsyncMock(return_value=MagicMock(status_code=200, text="ok"))
        with patch("httpx.AsyncClient", return_value=m):
            await client.respond_approval(run_id="r1", choice="session", resolve_all=True)
        assert m.post.call_args.kwargs["json"] == {"choice": "session", "all": True}

    @pytest.mark.asyncio
    async def test_409_raises_hermes_error(self):
        client = HermesServeClient(base_url=API_BASE, api_key=API_KEY)
        m = _mock_client()
        m.post = AsyncMock(return_value=MagicMock(status_code=409, text="approval_not_pending"))
        with patch("httpx.AsyncClient", return_value=m):
            with pytest.raises(HermesError):
                await client.respond_approval(run_id="r1", choice="once")


# ─── 6. stop_run ─────────────────────────────────────────────
class TestStopRun:
    """POST /v1/runs/{id}/stop。"""

    @pytest.mark.asyncio
    async def test_success(self):
        client = HermesServeClient(base_url=API_BASE, api_key=API_KEY)
        m = _mock_client()
        m.post = AsyncMock(return_value=MagicMock(status_code=204))
        with patch("httpx.AsyncClient", return_value=m):
            await client.stop_run("r1")  # 应正常返回不抛

    @pytest.mark.asyncio
    async def test_404_is_idempotent(self):
        """run 已结束返 404 也视为成功（幂等）。"""
        client = HermesServeClient(base_url=API_BASE, api_key=API_KEY)
        m = _mock_client()
        m.post = AsyncMock(return_value=MagicMock(status_code=404, text="run_not_found"))
        with patch("httpx.AsyncClient", return_value=m):
            await client.stop_run("r_done")  # 不抛


# ─── 7. get_run_status ───────────────────────────────────────
class TestGetRunStatus:
    @pytest.mark.asyncio
    async def test_returns_dict(self):
        client = HermesServeClient(base_url=API_BASE, api_key=API_KEY)
        m = _mock_client()
        m.get = AsyncMock(return_value=MagicMock(
            status_code=200,
            json=lambda: {"run_id": "r1", "status": "running", "last_event": "tool.started"},
        ))
        with patch("httpx.AsyncClient", return_value=m):
            status = await client.get_run_status("r1")
        assert status["status"] == "running"


# ─── 8. list_models ──────────────────────────────────────────
class TestListModels:
    @pytest.mark.asyncio
    async def test_returns_model_ids(self):
        client = HermesServeClient(base_url=API_BASE, api_key=API_KEY)
        m = _mock_client()
        m.get = AsyncMock(return_value=MagicMock(
            status_code=200,
            json=lambda: {"data": [{"id": "MiniMax-M3.0"}, {"id": "MiniMax-M2.7"}]},
        ))
        with patch("httpx.AsyncClient", return_value=m):
            models = await client.list_models()
        assert models == ["MiniMax-M3.0", "MiniMax-M2.7"]

    @pytest.mark.asyncio
    async def test_unreachable_returns_empty(self):
        client = HermesServeClient(base_url=API_BASE, api_key=API_KEY)
        with patch("httpx.AsyncClient", side_effect=httpx.ConnectError("refused")):
            models = await client.list_models()
        assert models == []


# ─── 9. 默认 base_url 兜底 ───────────────────────────────────
class TestDefaults:
    def test_default_base_url(self):
        """未设 HERMES_API_BASE_URL 环境变量时，HERMES_API_BASE_URL 常量应兜底到 :8642。"""
        # 默认值硬编码在 hermes_serve_client.py
        assert HERMES_API_BASE_URL == "http://127.0.0.1:8642" or "8642" in HERMES_API_BASE_URL

    def test_authorization_header_bearer(self):
        c = HermesServeClient(base_url=API_BASE, api_key="secret")
        h = c._headers()
        assert h["Authorization"] == "Bearer secret"
        assert h["Content-Type"] == "application/json"