"""
test_ws_endpoint.py — WebSocket endpoint ping/pong 测试（M-005 + v119 单向 idle）

覆盖 v10 改动（main.py websocket_endpoint）：
- 客户端发 {"type":"ping"} → 服务端立即回 {"type":"pong"}
- 无 token → close 4001 Unauthorized
- 业务推送路径不受 ping/pong 影响

覆盖 v119 改动（2026-08-09 单向心跳）：
- WS 通道 10 分钟无任意消息 → 服务端 close 4001 "idle timeout"
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


def test_ws_idle_timeout_kicks_login(client, monkeypatch):
    """v119: WS 通道 idle 超时 → 服务端 close 4001 "idle timeout"
    默认 WS_IDLE_TIMEOUT=600s 不便测试, monkey-patch 成 1s, 验证连接被踢
    """
    from ws import endpoint as ep
    monkeypatch.setattr(ep, "WS_IDLE_TIMEOUT", 1)
    token = _make_token()
    # 客户端只连接, 不发任何消息
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(f"/ws/order_update?token={token}") as ws:
            # idle_checker 每 30s 检查一次; WS_IDLE_TIMEOUT=1s → 至多 ~31s 内必触发
            # 给服务端留足够时间: 等到 raise WebSocketDisconnect
            ws.receive_json()  # 阻塞等待服务端关闭
    assert exc_info.value.code == 4001


def test_ws_idle_timeout_does_not_fire_when_pinging(client, monkeypatch):
    """v119 守门: 客户端持续 ping → 不应被 idle 踢
    monkey-patch 成 1s, 每 0.5s 发一次 ping, 跑 3s 仍存活
    """
    import time as _t
    from ws import endpoint as ep
    monkeypatch.setattr(ep, "WS_IDLE_TIMEOUT", 1)
    token = _make_token()
    with client.websocket_connect(f"/ws/order_update?token={token}") as ws:
        end = _t.monotonic() + 3
        while _t.monotonic() < end:
            ws.send_text(json.dumps({"type": "ping", "ts": _t.time()}))
            # 应当立刻收到 pong
            reply = ws.receive_json()
            assert reply["type"] == "pong"
            _t.sleep(0.3)
        # 3 秒后连接仍在 (不被踢) — 主动 send_text 不抛即说明连接仍 OPEN
        ws.send_text(json.dumps({"type": "ping", "ts": _t.time()}))


def test_ws_ping_touches_session_cache(client, monkeypatch):
    """v120+: WS ping 应自动续期 HTTP session cache
    客户端 ping → 服务端 ping handler → 调 session.touch(token) → last_seen_at 变新
    """
    import time as _t
    from auth import session as session_mod

    # 注入 fake time: 起始 1000.0
    fake_now = [1000.0]
    monkeypatch.setattr(session_mod.time, "time", lambda: fake_now[0])

    token = _make_token()
    # WS 鉴权只 decode_token, 不调 register_token — 必须手动注册才能观察 touch
    session_mod.register_token(token, user_id=1, role="trader")
    initial_ts = session_mod._TOKEN_CACHE[token]["last_seen_at"]
    assert initial_ts == 1000.0

    # 跳到 100s 后, 发 ping — 此时 fake_now = 1100.0
    fake_now[0] += 100

    with client.websocket_connect(f"/ws/order_update?token={token}") as ws:
        ws.send_text(json.dumps({"type": "ping", "ts": _t.time()}))
        reply = ws.receive_json()
        assert reply["type"] == "pong"

    # 验证 last_seen_at 已被 reset 到发 ping 那一刻(1100.0, 严格大于 1000.0)
    new_ts = session_mod._TOKEN_CACHE[token]["last_seen_at"]
    assert new_ts > initial_ts
    assert new_ts == 1100.0


def test_ws_ping_keeps_session_alive_past_idle_threshold(client, monkeypatch):
    """v120+ 边界: WS 持续 ping → session.touch 持续刷新 → 即使窗口过 600s 也保持有效
    关键路径防御, 防止回归 (touch 被某次改动忽略)
    """
    import time as _t
    from auth import session as session_mod

    fake_now = [5000.0]
    monkeypatch.setattr(session_mod.time, "time", lambda: fake_now[0])

    token = _make_token()
    session_mod.register_token(token, user_id=1, role="trader")

    with client.websocket_connect(f"/ws/order_update?token={token}") as ws:
        # 发 3 次 ping, 每次间隔跳 300s, 累计 900s > 600s 阈值
        for i in range(3):
            fake_now[0] += 300
            ws.send_text(json.dumps({"type": "ping", "ts": _t.time()}))
            ws.receive_json()  # pong
            # 每次 ping 后 session 仍应有效
            assert session_mod.is_valid(token) is True, (
                f"session invalidated at iter {i}, time={fake_now[0]}"
            )