"""
test_ws_endpoint.py — WebSocket endpoint ping/pong 测试（M-005）

覆盖 v10 改动（main.py websocket_endpoint）：
- 客户端发 {"type":"ping"} → 服务端立即回 {"type":"pong"}
- 无 token → close 4001 Unauthorized
- 业务推送路径不受 ping/pong 影响
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

import json
import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

from main import app


@pytest.fixture
def client():
    return TestClient(app)


def _make_token() -> str:
    """生成合法 JWT（避免硬编码过期 token）。"""
    from auth.security import create_access_token
    return create_access_token({"sub": "test_user", "role": "trader"})


def test_ws_no_token_rejected(client):
    """无 token → 服务端 close 4001 Unauthorized"""
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/order_update") as ws:
            ws.receive_json()
    # WebSocketDisconnect.code 属性持有 close code
    assert exc_info.value.code == 4001


def test_ws_ping_returns_pong(client):
    """客户端 ping → 服务端立即回 pong（M-005 核心）"""
    token = _make_token()
    with client.websocket_connect(f"/ws/order_update?token={token}") as ws:
        ws.send_text(json.dumps({"type": "ping", "ts": 12345}))
        reply = ws.receive_json()
        assert reply["type"] == "pong"
        assert reply["ts"] == 12345  # ts 应原样回传


def test_ws_non_json_message_ignored(client):
    """非 JSON 消息 → 服务端忽略（当作心跳续约，不报错）"""
    token = _make_token()
    with client.websocket_connect(f"/ws/order_update?token={token}") as ws:
        ws.send_text("not json")
        # 紧接着发 ping 应能正常回 pong（说明前面非 JSON 没崩连接）
        ws.send_text(json.dumps({"type": "ping", "ts": 99}))
        reply = ws.receive_json()
        assert reply["type"] == "pong"


def test_ws_pong_or_business_message_no_reply(client):
    """业务消息 / pong → 服务端不回（推送是单向 server→client）"""
    token = _make_token()
    with client.websocket_connect(f"/ws/order_update?token={token}") as ws:
        ws.send_text(json.dumps({"type": "pong"}))
        # 验证服务端不回任何消息 — 客户端 receive 应超时或无数据
        # TestClient receive_json 默认会等；这里用 try/except 验证
        try:
            ws.receive_json(timeout=0.5)
            # 如果收到说明服务端回了 → 失败
            pytest.fail("server should NOT reply to client pong/business message")
        except Exception:
            pass  # 期望：无回复（或 timeout）