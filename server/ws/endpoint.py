"""
ws/endpoint.py — /ws/{channel} WebSocket 端点（单向心跳 + 订阅推送）

行为：
- 通过 ?token=JWT 认证，无 token → close 4001
- 接入 ws_manager（按 channel 维护连接集）
- 单向心跳：
  - 客户端 30s 主动发 ping → 服务端立即回 pong（重置 last_recv）
  - 服务端**不**主动 ping
  - 服务端 10 分钟内没收到**任意**消息（ping / pong / 业务）→ close 4001 "idle timeout"
    → 前端 onclose 看 4001 → 跳登录、停止重连
  - 10 分钟阈值与 HTTP session 完全解耦（WS 鉴权只 decode_token，不动 session cache）
- 业务消息：
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
import os
import tempfile
import time
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import logging

log = logging.getLogger(__name__)

from server.auth.security import decode_token
from server.auth.session import touch as session_touch  # WS ping 续期 HTTP session
from server.infra.db import SessionLocal
from server.ws.manager import ws_manager, match_pattern
from server.repo.quote_snapshots import get_latest_multi as repo_get_latest_multi, to_dict as repo_to_dict
from server.tables import Users


WS_IDLE_TIMEOUT = 600  # 秒：WS 通道无任意消息的最大容忍（客户端 30s ping → 10 分钟内必收到消息）
# 测试时可 monkey-patch 成小值（默认 600s 测试不现实）

# sync_update 频道鉴权: admin role required
WS_CHANNELS_REQUIRE_ADMIN = {"sync_update"}


def _resolve_ws_user(token: str):
    """WS 鉴权: 合法 JWT → claims; 否则 None。

    仅接受合法 JWT 鉴权; 不再有 hardcoded admin 凭证捷径 (2026-08-25 cleanup-ai-remove)。
    """
    return decode_token(token)


def register_ws_endpoint(app: FastAPI):
    """注册 /ws/{channel} WebSocket 端点到 FastAPI app。

    抽成函数避免 main.py 臃肿；FastAPI 启动时会调 register，
    endpoint 闭包绑定 channel/manager 等 module-level 单例。
    """

    @app.websocket("/ws/{channel}")
    async def websocket_endpoint(websocket: WebSocket, channel: str):
        """前端订阅推送。channel ∈ order_update | trade_update | quote_update | strategy_update | sync_update。

        通过 query param ?token=JWT 认证；无 token 则拒绝连接。

        心跳（单向）：
          - 客户端 30s 主动 ping → 服务端立即回 pong（重置 last_recv），服务端不主动 ping
          - 服务端 10 分钟无任意消息 → close 4001 "idle timeout"
          - WS 鉴权只 decode_token，不调 session.is_valid
          - ping handler 调 session.touch(token)，让 WS 通信时自动续期 HTTP session，
            保持"WS 真断 → HTTP session 也跟着过期"的语义（WS 断了 ping 就停了 →
            idle_checker 10min 后关 WS + session 自然过期）
        业务消息：
          - subscribe / unsubscribe 处理；subscribe_ack 立即从 quote_snapshots 读最新快照（最新一条 22 字段）
          - sync_update 频道（admin only），鉴权校验 role=admin（其他 channel 不变）
        """
        token = websocket.query_params.get("token")
        if not token:
            await websocket.close(code=4001, reason="Unauthorized")
            return
        user = _resolve_ws_user(token)
        if not user:
            await websocket.close(code=4001, reason="Invalid token")
            return
        # sync_update admin 鉴权
        if channel in WS_CHANNELS_REQUIRE_ADMIN:
            # 从 DB 查 role(避免 JWT 缓存了旧 role)
            user_row = Users.query_one(id=int(user.get("id") or user.get("sub", 0)))
            if not user_row or user_row.role != "admin":
                await websocket.close(code=4003, reason="Admin required")
                return
        await ws_manager.connect(websocket, channel)
        user_id = int(user.get("id") or user.get("sub", 0)) or None

        last_recv = asyncio.get_event_loop().time()

        async def idle_checker():
            """WS 通道独立 idle 计时（不与 HTTP session 耦合）
            客户端 30s 必发 ping → 10 分钟内必收到任意消息 → 否则视为前后端断开, T 掉节省资源
            """
            try:
                while True:
                    await asyncio.sleep(30)
                    now = asyncio.get_event_loop().time()
                    if now - last_recv > WS_IDLE_TIMEOUT:
                        await websocket.close(code=4001, reason="idle timeout")
                        return
            except (WebSocketDisconnect, Exception):
                return

        idle_task = asyncio.ensure_future(idle_checker())  # Py3.6.8 compat
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
                    # 用 WS ping 自动续期 HTTP session cache。
                    # 客户端 30s ping → last_seen_at 持续刷新,
                    # 保证只要 WS 还活着, session 就不会因 10 分钟 idle 过期。
                    # touch() 已是幂等 no-op: token 不在 cache 时静默 return。
                    session_touch(token)
                    await websocket.send_json({"type": "pong", "ts": parsed.get("ts")})
                    continue
                # 订阅协议: 支持 pattern (子串匹配)
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
                    except ValueError as e:
                        await websocket.send_json({
                            "type": "subscribe_ack", "code": 429, "msg": str(e),
                            "stock_codes": [],
                            "snapshots": {},
                        })
                        continue
                    # 把 subscribe 事件持久化到专属 log,便于外部观察前端是否触发。
                    # 用 gettempdir() 下的固定路径 + 全量 try/except: 诊断日志失败只 print, 绝不打断连接
                    try:
                        _log_path = os.path.join(tempfile.gettempdir(), 'ws_subscribes.log')
                        with open(_log_path, 'a') as _f:
                            _f.write(f"[subscribe] ts={int(time.time())} remote={websocket.client[0] if websocket.client else '?'} accepted={sorted(accepted)} sub_total={len(ws_manager.subscription_index)} active={len(ws_manager.active_connections.get('quote_update', set()))}\n")
                    except Exception:
                        print("[ws-subscribe] debug log write failed (non-fatal)", flush=True)
                    # 立即返当前最新快照
                    # 只对 "精确 stock_code pattern" 查 DB 拿 snapshot
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
                        # 快照查询包进 try/except —— 任何 DB 异常都不应打挂连接,
                        #   降级为返回空 snapshots (订阅本身已生效, 后续 tick 会补数据)
                        db = SessionLocal()
                        try:
                            rows = repo_get_latest_multi(db, exact_patterns)
                            snapshots = {c: repo_to_dict(s) for c, s in rows.items()}
                            matched_count = len(snapshots)
                        except Exception:
                            print("[ws-subscribe] snapshot query failed (non-fatal)", flush=True)
                        finally:
                            db.close()
                    await websocket.send_json({
                        "type": "subscribe_ack", "code": 0, "msg": "",
                        "stock_codes": sorted(accepted),
                        "snapshots": snapshots,
                        # 让前端知道是否有宽泛 pattern (后面会持续推 tick)
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
            idle_task.cancel()
            ws_manager.disconnect(websocket, channel)