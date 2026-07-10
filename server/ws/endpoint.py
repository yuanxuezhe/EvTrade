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
from server.ws.manager import ws_manager, match_pattern
from server.repo.quote_snapshots import get_latest_multi as repo_get_latest_multi, to_dict as repo_to_dict
from server.models.user import User as UserModel  # 2026-07-10 sync_update admin 鉴权


WS_HEARTBEAT_INTERVAL = 30  # 秒：服务端主动 ping 间隔
WS_CLIENT_TIMEOUT = 60      # 秒：上次消息到现在的最大间隔（= 2 × heartbeat）

# 2026-07-10 sync_update 频道鉴权:admin role required
WS_CHANNELS_REQUIRE_ADMIN = {"sync_update"}


def register_ws_endpoint(app: FastAPI):
    """注册 /ws/{channel} WebSocket 端点到 FastAPI app。

    抽成函数避免 main.py 臃肿；FastAPI 启动时会调 register，
    endpoint 闭包绑定 channel/manager 等 module-level 单例。
    """

    @app.websocket("/ws/{channel}")
    async def websocket_endpoint(websocket: WebSocket, channel: str):
        """前端订阅推送。channel ∈ order_update | trade_update | quote_update | strategy_update | sync_update。

        通过 query param ?token=JWT 认证；无 token 则拒绝连接。

        v10 心跳：双向 ping/pong
        v15 增（2026-07-09 quote-snapshot-subscribe）：
          - quote_update 频道也启服务端主动 ping（之前因"走 hqserver"误跳）
          - 业务消息处理：subscribe / unsubscribe
          - subscribe_ack 立即从 quote_snapshots 读最新快照（最新一条 22 字段）
        v21 增（2026-07-10 stock-info-crawler）：
          - sync_update 频道（admin only）
          - 鉴权校验 role=admin（其他 channel 不变）
        """
        token = websocket.query_params.get("token")
        if not token:
            await websocket.close(code=4001, reason="Unauthorized")
            return
        user = decode_token(token)
        if not user:
            await websocket.close(code=4001, reason="Invalid token")
            return
        # 2026-07-10 sync_update admin 鉴权
        if channel in WS_CHANNELS_REQUIRE_ADMIN:
            # 从 DB 查 role(避免 JWT 缓存了旧 role)
            db = SessionLocal()
            try:
                user_row = db.query(UserModel).filter_by(id=int(user.get("id") or user.get("sub", 0))).first()
                if not user_row or user_row.role != "admin":
                    await websocket.close(code=4003, reason="Admin required")
                    return
            finally:
                db.close()
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
                # 2026-07-10 quote-pattern-subscribe: 升级支持 pattern (子串匹配)
                #   - '000001.SZ' 精确 / 'SZ' 市场 / '' 全市场 都走同一规则
                if msg_type == "subscribe" and channel == "quote_update":
                    codes_raw = parsed.get("stock_codes") or []
                    print(f"[ws-subscribe] received codes={codes_raw}", flush=True)
                    if not isinstance(codes_raw, list):
                        await websocket.send_json({
                            "type": "subscribe_ack", "code": 400, "msg": "stock_codes must be list",
                            "stock_codes": [],
                            "snapshots": {},
                        })
                        continue
                    try:
                        accepted = ws_manager.subscribe(websocket, codes_raw)
                        # 2026-07-09 quick verify: 把 subscribe 事件持久化到专属 log,便于外部观察前端是否触发
                        with open('/tmp/ws_subscribes.log', 'a') as _f:
                            _f.write(f"[subscribe] ts={int(__import__('time').time())} remote={websocket.client[0] if websocket.client else '?'} accepted={sorted(accepted)} sub_total={len(ws_manager.subscription_index)} active={len(ws_manager.active_connections.get('quote_update', set()))}\n")
                    except ValueError as e:
                        await websocket.send_json({
                            "type": "subscribe_ack", "code": 429, "msg": str(e),
                            "stock_codes": [],
                            "snapshots": {},
                        })
                        continue
                    # 立即返当前最新快照
                    # 2026-07-10 升级: 只对 "精确 stock_code pattern" 查 DB 拿 snapshot
                    #   'SZ' / 'SH' / '000001' / '' 都是 pattern, 不能直接当 stock_code 查 DB
                    #   这些 pattern 的 snapshot 通过后续 tick 推送 (无需 ack 立即返)
                    #   "精确" 定义: 含 '.' 且长度 >= 6 (如 '000001.SZ' / '600000.SH')
                    exact_patterns = []
                    has_wildcard = False
                    for p in accepted:
                        if "." in p and len(p) >= 6:
                            exact_patterns.append(p)
                        else:
                            has_wildcard = True
                    snapshots = {}
                    matched_count = 0
                    if exact_patterns:
                        db = SessionLocal()
                        try:
                            rows = repo_get_latest_multi(db, exact_patterns)
                            snapshots = {c: repo_to_dict(s) for c, s in rows.items()}
                            matched_count = len(snapshots)
                        finally:
                            db.close()
                    await websocket.send_json({
                        "type": "subscribe_ack", "code": 0, "msg": "",
                        "stock_codes": sorted(accepted),
                        "snapshots": snapshots,
                        # 2026-07-10 新增: 让前端知道是否有宽泛 pattern (后面会持续推 tick)
                        "has_wildcard": has_wildcard,
                        "snapshot_count": matched_count,
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