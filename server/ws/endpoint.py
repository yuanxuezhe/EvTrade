"""
ws/endpoint.py — /ws/{channel} WebSocket 端点（v10 ping/pong 心跳）

行为：
- 通过 ?token=JWT 认证，无 token → close 4001
- 接入 ws_manager（按 channel 维护连接集）
- 双向心跳：
  - 收到 client `{"type":"ping"}` → 立即回 `{"type":"pong"}`
  - 服务端 30s 主动发 ping（quote_update 频道除外 — 走 hqserver :8765）
  - 60s 内没收到任何消息 → close 4408
- 推送是单向 server→client，不在 receive_text 中处理业务消息
"""
import asyncio
import json
import time
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from server.auth.security import decode_token
from server.ws.manager import ws_manager


WS_HEARTBEAT_INTERVAL = 30  # 秒：服务端主动 ping 间隔
WS_CLIENT_TIMEOUT = 60      # 秒：上次消息到现在的最大间隔（= 2 × heartbeat）


def register_ws_endpoint(app: FastAPI):
    """注册 /ws/{channel} WebSocket 端点到 FastAPI app。

    抽成函数避免 main.py 臃肿；FastAPI 启动时会调 register，
    endpoint 闭包绑定 channel/manager 等 module-level 单例。
    """

    @app.websocket("/ws/{channel}")
    async def websocket_endpoint(websocket: WebSocket, channel: str):
        """前端订阅推送。channel ∈ order_update | trade_update（quote_update 走 hqserver :8765，不在此端点处理）。

        change consolidate-position-data-flow: position_update / asset_update 频道已删除
        (xtquant broker 不发 pos_cfm / ast_cfm, 改由 trd_cfm 增量 + day-init reconcile 兜底).

        通过 query param ?token=JWT 认证；无 token 则拒绝连接。

        v10 增：ping/pong 双向心跳防 idle close。
          - 收到 {"type":"ping"} → 回 {"type":"pong"}（立即响应）
          - 启动 30s 间隔服务端主动 ping（保活 + 探活）
          - 60s 内没收到任何客户端消息 → close 4408 (timeout)
        """
        token = websocket.query_params.get("token")
        if not token or not decode_token(token):
            await websocket.close(code=4001, reason="Unauthorized")
            return
        await ws_manager.connect(websocket, channel)

        last_recv = asyncio.get_event_loop().time()

        async def heartbeat_sender():
            """服务端主动 ping；只在 channel != quote_update 时启动（quote 走 hqserver）。"""
            if channel == "quote_update":
                return  # quote 直连 hqserver :8765，不走后端 ws
            try:
                while True:
                    await asyncio.sleep(WS_HEARTBEAT_INTERVAL)
                    await websocket.send_json({"type": "ping", "ts": time.time()})
                    # 超时检查：上次收到消息 > WS_CLIENT_TIMEOUT 秒 → 主动断开
                    now = asyncio.get_event_loop().time()
                    if now - last_recv > WS_CLIENT_TIMEOUT:
                        await websocket.close(code=4408, reason="heartbeat timeout")
                        return
            except (WebSocketDisconnect, Exception):
                return

        sender_task = asyncio.ensure_future(heartbeat_sender())  # Py3.6.8 compat
        try:
            while True:
                data = await websocket.receive_text()
                last_recv = asyncio.get_event_loop().time()
                # ping/pong：客户端主动 ping → 服务端立即回 pong
                try:
                    parsed = json.loads(data)
                except (json.JSONDecodeError, ValueError):
                    continue  # 非 JSON 当心跳续约忽略
                if isinstance(parsed, dict) and parsed.get("type") == "ping":
                    await websocket.send_json({"type": "pong", "ts": parsed.get("ts")})
                # pong / 业务消息：当作心跳续约，不再做业务处理（推送是单向 server→client）
        except WebSocketDisconnect:
            pass
        except Exception as e:
            print(f"[WS] error on {channel}: {e}")
        finally:
            sender_task.cancel()
            ws_manager.disconnect(websocket, channel)
