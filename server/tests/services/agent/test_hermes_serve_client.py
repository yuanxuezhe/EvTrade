"""
server/tests/services/agent/test_hermes_serve_client.py — HermesServeClient 单测

Mock httpx + websockets（不依赖真实 hermes serve daemon）。
"""
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 在 import 之前设 JWT_SECRET
os.environ.setdefault("JWT_SECRET", "test_secret_for_unit_test_only_32bytes!!")
os.environ.setdefault("JWT_ALGORITHM", "HS256")

from server.services.agent.hermes_serve_client import (  # noqa: E402
    HermesServeClient,
    HermesEvent,
    HermesUnreachableError,
    HermesError,
)


# ─── 1. is_reachable ─────────────────────────────────────────────
class TestIsReachable:
    @pytest.mark.asyncio
    async def test_healthy_returns_true(self):
        client = HermesServeClient(base_url="http://test:9119")
        mock_resp = MagicMock(status_code=200)

        # httpx.AsyncClient() 返回 async ctx mgr；__aenter__ 返回 mock_client
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)

        async_ctx = MagicMock()
        async_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        async_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=async_ctx):
            result = await client.is_reachable()
        assert result is True

    @pytest.mark.asyncio
    async def test_unreachable_returns_false(self):
        client = HermesServeClient(base_url="http://127.0.0.1:1")
        # 连不存在的端口 → httpx.RequestError
        result = await client.is_reachable()
        assert result is False


# ─── 2. _rpc ─────────────────────────────────────────────────────
class TestRpc:
    @pytest.mark.asyncio
    async def test_success(self):
        client = HermesServeClient()
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}
        with patch("httpx.AsyncClient") as mock_async:
            mock_async.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_resp
            )
            result = await client._rpc("test.method", {"x": 1})
        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_rpc_error_in_response(self):
        client = HermesServeClient()
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {
            "jsonrpc": "2.0", "id": 1,
            "error": {"code": -1, "message": "bad params"},
        }
        with patch("httpx.AsyncClient") as mock_async:
            mock_async.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_resp
            )
            with pytest.raises(HermesError, match="bad params"):
                await client._rpc("test.method", {})

    @pytest.mark.asyncio
    async def test_network_error_raises_unreachable(self):
        client = HermesServeClient()
        with patch("httpx.AsyncClient") as mock_async:
            mock_async.return_value.__aenter__.return_value.post = AsyncMock(
                side_effect=__import__("httpx").ConnectError("conn refused")
            )
            with pytest.raises(HermesUnreachableError):
                await client._rpc("test.method", {})


# ─── 3. start_run ────────────────────────────────────────────────
class TestStartRun:
    @pytest.mark.asyncio
    async def test_returns_run_id(self):
        client = HermesServeClient()
        with patch.object(client, "_rpc", AsyncMock(return_value={"run_id": "r-abc-123"})):
            run_id = await client.start_run(
                session_id="s1", user_message="hello", tools=[]
            )
        assert run_id == "r-abc-123"

    @pytest.mark.asyncio
    async def test_missing_run_id_raises(self):
        client = HermesServeClient()
        with patch.object(client, "_rpc", AsyncMock(return_value={"ok": True})):
            with pytest.raises(HermesError, match="missing run_id"):
                await client.start_run(session_id="s1", user_message="x", tools=[])


# ─── 4. HermesEvent.from_dict ────────────────────────────────────
class TestHermesEvent:
    def test_from_dict_text_event(self):
        e = HermesEvent.from_dict({"type": "text", "content": "hi"})
        assert e.type == "text"
        assert e.content == "hi"

    def test_from_dict_tool_call_event(self):
        e = HermesEvent.from_dict({
            "type": "tool_call",
            "tool_name": "place_order",
            "tool_call_id": "tc-1",
            "tool_params": {"stock_code": "600000.SH"},
        })
        assert e.tool_name == "place_order"
        assert e.tool_call_id == "tc-1"
        assert e.tool_params["stock_code"] == "600000.SH"

    def test_from_dict_minimal(self):
        e = HermesEvent.from_dict({"type": "step_start"})
        assert e.type == "step_start"
        assert e.run_id == ""
        assert e.tool_params == {}


# ─── 5. subscribe_events (mock websockets) ──────────────────────
class TestSubscribeEvents:
    @pytest.mark.asyncio
    async def test_yields_events_then_complete(self):
        client = HermesServeClient()

        # Mock websockets.connect → AsyncMock context manager
        async def fake_recv():
            yield_idx = fake_recv.i
            fake_recv.i += 1
            frames = [
                '{"type":"step_start"}',
                '{"type":"text","content":"hello"}',
                '{"type":"tool_call","tool_name":"list_positions","tool_call_id":"tc-1","tool_params":{}}',
                '{"type":"tool_result","tool_result":{"ok":true}}',
                '{"type":"agent_complete"}',
            ]
            if yield_idx < len(frames):
                return frames[yield_idx]
            raise __import__("asyncio").TimeoutError()
        fake_recv.i = 0

        mock_ws = MagicMock()
        mock_ws.recv = fake_recv

        class FakeConnect:
            def __init__(self, *a, **kw): pass
            async def __aenter__(self): return mock_ws
            async def __aexit__(self, *a): return False

        with patch("websockets.connect", FakeConnect):
            events = []
            async for e in client.subscribe_events("r-1"):
                events.append(e)
        assert len(events) == 5
        assert events[0].type == "step_start"
        assert events[1].content == "hello"
        assert events[2].tool_name == "list_positions"
        assert events[3].tool_result == {"ok": True}
        assert events[4].type == "agent_complete"


# ─── 6. list_available_tools ────────────────────────────────────
class TestListAvailableTools:
    @pytest.mark.asyncio
    async def test_returns_tools(self):
        client = HermesServeClient()
        with patch.object(
            client, "_rpc",
            AsyncMock(return_value={"tools": [{"name": "web_search"}]}),
        ):
            tools = await client.list_available_tools()
        assert tools == [{"name": "web_search"}]

    @pytest.mark.asyncio
    async def test_unreachable_returns_empty(self):
        client = HermesServeClient()
        with patch.object(client, "_rpc", AsyncMock(side_effect=HermesUnreachableError("x"))):
            tools = await client.list_available_tools()
        assert tools == []


# ─── 7. respond_confirmation ────────────────────────────────────
class TestRespondConfirmation:
    @pytest.mark.asyncio
    async def test_calls_rpc(self):
        client = HermesServeClient()
        with patch.object(client, "_rpc", AsyncMock(return_value={})) as mock_rpc:
            await client.respond_confirmation(
                run_id="r-1", tool_call_id="tc-1", confirmed=True,
            )
        mock_rpc.assert_called_once_with(
            "run.confirm",
            {"run_id": "r-1", "tool_call_id": "tc-1", "confirmed": True},
        )
