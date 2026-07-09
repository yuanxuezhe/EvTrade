"""
ws/endpoint.py — /ws/{channel} WebSocket 端点（v10 ping/pong 心跳 + v15 subscribe 协议）

行为：
- 通过 ?token=JWT 认证，无 token → close 4001
- 接入 ws_manager（按 channel 维护连接集）
- 双向心跳：
  - 收到 client `{"type":"ping"}` → 立即回 `{"type":"pong"}`
  - 服务端 30s 主动发 ping（所有 channel 都启，含 quote_update）
  - 60s 内没收到任何消息 → close 4408
- 业务消息（v15 新增, 2026-07-09 quote-snapshot-subscribe）：
  - 收到 client `{"type":"subscribe", "stock_codes":[...]}` →
      - 调 ws_manager.subscribe(ws, codes)
      - 立即返 `{"type":"subscribe_ack", "stock_codes":[...], "snapshots":{...}}`
        （从 quote_snapshots 表读最新 1 行, 无记录则不返）
      - 后续 quote_consumer 推 quote_update 时, 按 stock_code 倒排索引过滤推送
  - 收到 client `{"type":"unsubscribe", "stock_codes":[...]}` →
      - 调 ws_manager.unsubscribe(ws, codes)
      - 立即返 `{"type":"unsubscribe_ack", "stock_codes":[...]}`
"""
import asyncio
import json
import time
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from server.auth.security import decode_token
from server.db import SessionLocal
from server.ws.manager import ws_manager
from server.repo.quote_snapshots import get_latest_multi as repo_get_latest_multi, to_dict as repo_to_dict


WS_HEARTBEAT_INTERVAL = 30  # 秒：服务端主动 ping 间隔
WS_CLIENT_TIMEOUT = 60      # 秒：上次消息到现在的最大间隔（= 2 × heartbeat）


def register_ws_endpoint(app: FastAPI):
    """注册 /ws/{channel} WebSocket 端点到 FastAPI app。

    抽成函数避免 main.py 臃肿；FastAPI 启动时会调 register，
    endpoint 闭包绑定 channel/manager 等 module-level 单例。
    """

    @app.websocket("/ws/{channel}")
    async def websocket_endpoint(websocket: WebSocket, channel: str):
        """前端订阅推送。channel ∈ order_update | trade_update | quote_update | strategy_update。

        通过 query param ?token=JWT 认证；无 token 则拒绝连接。

        v10 心跳：双向 ping/pong
        v15 增（2026-07-09 quote-snapshot-subscribe）：
          - quote_update 频道也启服务端主动 ping（之前因"走 hqserver"误跳）
          - 业务消息处理：subscribe / unsubscribe
          - subscribe_ack 立即从 quote_snapshots 读最新快照（最新一条 22 字段）
        """
        token = websocket.query_params.get("token")
        if not token or not decode_token(token):
            await websocket.close(code=4001, reason="Unauthorized")
            return
        await ws_manager.connect(websocket, channel)

        last_recv = asyncio.get_event_loop().time()

        async def heartbeat_sender():
            """服务端主动 ping（所有 channel 都启）"""
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
                # 解析
                try:
                    parsed = json.loads(data)
                except (json.JSONDecodeError, ValueError):
                    continue  # 非 JSON 当心跳续约忽略
                if not isinstance(parsed, dict):
                    continue
                msg_type = parsed.get("type")
                # ping/pong：客户端主动 ping → 服务端立即回 pong
                if msg_type == "ping":
                    await websocket.send_json({"type": "pong", "ts": parsed.get("ts")})
                    continue
                # 2026-07-09 quote-snapshot-subscribe: 订阅协议
                if msg_type == "subscribe" and channel == "quote_update":
                    codes_raw = parsed.get("stock_codes") or []
                    if not isinstance(codes_raw, list):
                        await websocket.send_json({
                            "type": "subscribe_ack", "code": 400, "msg": "stock_codes must be list",
                            "stock_codes": [],
                            "snapshots": {},
                        })
                        continue
                    try:
                        accepted = ws_manager.subscribe(websocket, codes_raw)
                    except ValueError as e:
                        await websocket.send_json({
                            "type": "subscribe_ack", "code": 429, "msg": str(e),
                            "stock_codes": [],
                            "snapshots": {},
                        })
                        continue
                    # 立即返当前最新快照（quote_snapshots 表读 latest）
                    snapshots = {}
                    if accepted:
                        db = SessionLocal()
                        try:
                            rows = repo_get_latest_multi(db, list(accepted))
                            snapshots = {c: repo_to_dict(s) for c, s in rows.items()}
                        finally:
                            db.close()
                    await websocket.send_json({
                        "type": "subscribe_ack", "code": 0, "msg": "",
                        "stock_codes": sorted(accepted),
                        "snapshots": snapshots,
                    })
                    continue
                if msg_type == "unsubscribe" and channel == "quote_update":
                    codes_raw = parsed.get("stock_codes") or []
                    if not isinstance(codes_raw, list):
                        await websocket.send_json({
                            "type": "unsubscribe_ack", "code": 400, "msg": "stock_codes must be list",
                            "stock_codes": [],
                        })
                        continue
                    removed = ws_manager.unsubscribe(websocket, codes_raw)
                    await websocket.send_json({
                        "type": "unsubscribe_ack", "code": 0, "msg": "",
                        "stock_codes": sorted(removed),
                    })
                    continue
                # 其他业务消息：当作心跳续约，不做业务处理（推送是单向 server→client）
        except WebSocketDisconnect:
            pass
        except Exception as e:
            print(f"[WS] error on {channel}: {e}")
        finally:
            sender_task.cancel()
            ws_manager.disconnect(websocket, channel)