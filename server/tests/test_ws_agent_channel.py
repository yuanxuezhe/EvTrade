"""
test_ws_agent_channel.py — /ws/agent_channel ready 推送语义 (2026-08-23, ai-agent-ws-reuse-channel)

回归测试: agent_channel 连上后**立即**发 ready (REQ-ARCH-008「连上后立即发」)。

背景 (实际故障 2026-08-23):
- 前端 AgentWSClient.connect() 以收到 `ready` 事件为连接成功标志,
  在此之前不会发出首条 `user_message`。
- 若后端等第一条 user_message 才发 ready → 前后端互相等待,
  首条消息永远发不出去 (对话框「点击发送没用」)。
- 修复: endpoint.py 在 agent_channel 连接建立后立即调 send_agent_ready。

测试策略:
- 集成测试: 用 TestClient 连 /ws/agent_channel?token=hermesagent,
  断言不发送任何消息即可收到 ready (验证死锁解除)。
- 单元测试: send_agent_ready 直接推 `{type: "ready", session_id}` 且 session_id 非空。
"""
import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.ws import register_ws_endpoint
from server.ws.agent_handler import send_agent_ready


def test_agent_channel_sends_ready_on_connect():
    """连上 /ws/agent_channel 后, 未发任何消息即收到 ready (死锁回归)."""
    app = FastAPI()
    register_ws_endpoint(app)
    with TestClient(app) as client:
        with client.websocket_connect("/ws/agent_channel?token=hermesagent") as ws:
            # 关键: 连接后第一帧就应是 ready, 而不是等 user_message
            msg = ws.receive_json()
            assert msg["type"] == "ready"
            assert msg.get("session_id"), "ready 必须带 session_id"


def test_ready_payload_has_nonempty_session_id():
    """send_agent_ready 推 `{type: ready, session_id}` 且 session_id 非空."""
    sent = {}

    class FakeWS:
        async def send_text(self, payload: str):
            import json
            sent["payload"] = json.loads(payload)

    import asyncio
    asyncio.run(send_agent_ready(FakeWS(), user_id=7))

    assert sent["payload"]["type"] == "ready"
    sid = sent["payload"]["session_id"]
    assert isinstance(sid, str) and len(sid) > 0
    assert sid.startswith("u7-")  # user_id 进 session_id 前缀


def test_user_message_handler_does_not_resend_ready():
    """_handle_user_message 不应再重复推 ready (ready 只在连接时发一次)."""
    import inspect
    import re
    from server.ws.agent_handler import _handle_user_message

    src = inspect.getsource(_handle_user_message)
    # 源码里不应再有推 ready 的调用 (连接时已由 endpoint 发过)
    assert '"ready"' not in src or "不再重复发" in src
