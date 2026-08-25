"""
ws/endpoint.py — /ws/{channel} WebSocket 端点（单向心跳 + 订阅推送 + agent_channel 双向）

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
  - 收到 client agent_channel 消息（"user_message" / "confirmation"）→ 启动 hermes agent run
    （详见 server.ws.agent_handler 模块）
"""
import asyncio
import json
import os
import tempfile
import time
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import logging

log = logging.getLogger(__name__)

from server.auth.security import decode_token, HERMES_AGENT_TOKEN
from server.auth.session import touch as session_touch  # WS ping 续期 HTTP session
from server.infra.db import SessionLocal
from server.ws.manager import ws_manager, match_pattern
from server.repo.quote_snapshots import get_latest_multi as repo_get_latest_multi, to_dict as repo_to_dict
from server.tables import Users
# 2026-08-24 重做: agent_channel 改调 server.ai.agent_spawner (claudedemo 模式)
# 删除旧的 server.ws.agent_handler / server.services.agent.* 依赖
from server.ai.agent_spawner import ClaudeSession, _which_claude
from server.ai.mcp_server import get_mcp_server


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
        # agent_channel 需要的 user_id（连接级, 供 ready / 业务消息共用）
        user_id = int(user.get("id") or user.get("sub", 0)) or None
        if channel == "agent_channel":
            # 2026-08-24 重做: claude 未 spawn 也发 ready (claudedemo 同款).
            # ready 事件先于首条 user_message 到达, 前端才能确认 WS 双向通.
            # claude 实际 spawn 推迟到首条 user_message (懒初始化).
            import uuid as _uuid_mod
            session_id = f"u{user_id or 0}-{_uuid_mod.uuid4().hex[:12]}"
            await websocket.send_json({
                "type": "ready",
                "session_id": session_id,
            })

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
                # agent_channel (2026-08-24 重做): claudedemo 模式
                #   - WS 收到 user_message → spawner.run_turn(text) → 推流式 event 给前端
                #   - 旧 self-built JSON-RPC/Hermes 链路已删 (server.ws.agent_handler / server.services.agent.*)
                #   - claude -p 子进程 + --mcp-config 指向本进程内的 server.ai.mcp_server
                if channel == "agent_channel":
                    await _handle_agent_message(websocket, parsed, user_id=user_id)
                    continue
                # 其他业务消息：当作心跳续约，不做业务处理（推送是单向 server→client）
        except WebSocketDisconnect:
            pass
        except Exception as e:
            print(f"[WS] error on {channel}: {e}")
        finally:
            idle_task.cancel()
            ws_manager.disconnect(websocket, channel)


# ────────────────────────────────────────────────────────────────────────
# agent_channel 消息处理 (2026-08-24 重做: claudedemo 模式)
# ────────────────────────────────────────────────────────────────────────
async def _handle_agent_message(websocket: WebSocket, parsed: dict, user_id: int | None) -> None:
    """agent_channel 单条消息分发.

    支持 type:
      - user_message: {text, session_id?, history?} → spawn claude -p + stream events
      - ping: 已被 endpoint 主循环处理 (这里兜底)
      - stop: 暂不实现 (每 turn 是独立 claude -p, kill 由 idle / disconnect 兜底)
    """
    msg_type = parsed.get("type")

    if msg_type == "user_message":
        text = (parsed.get("text") or "").strip()
        session_id = parsed.get("session_id") or ""
        history = parsed.get("history") or []
        if not text:
            await websocket.send_json({"type": "error", "message": "empty message"})
            return

        # 检查 MCP server 是否已启动 (lifespan 必须先 set_mcp_server)
        mcp_srv = get_mcp_server()
        if mcp_srv is None:
            await websocket.send_json({
                "type": "error",
                "message": "EvTrade AI 助手未启动 (mcp_server is None). 确认 server.ai lifespan 起好.",
            })
            return

        # 检查 claude CLI 是否在 PATH
        if _which_claude() is None:
            # 推 error 事件 (前端 toast / tooltip 展示)
            await websocket.send_json({
                "type": "error",
                "message": (
                    "未在 PATH 中找到 `claude` CLI. EvTrade AI 助手 (claudedemo 模式) "
                    "需要本机或容器内有 claude binary. 安装: `npm i -g @anthropic-ai/claude-code`."
                ),
            })
            # 追加推 agent_complete 事件 — 让前端 onRunCompleted 能清 isThinking
            # 否则 spinner 会卡死 (前端 store.run_turn_started 但没收到 complete)
            await websocket.send_json({
                "type": "agent_complete",
                "success": False,
                "error": "claude_cli_missing",
                "session_id": session_id,
            })
            return

        # 推 run.started 先于 SSE 事件 (前端可立即把消息标为「agent 正在响应」)
        await websocket.send_json({
            "type": "run.started",
            "session_id": session_id,
            "user_id": user_id,
        })

        # spawn claude -p 子进程 + 流式推 AgentEvent
        session = ClaudeSession(
            mcp_port=mcp_srv.port,
            user_id=user_id,
            session_id=session_id,
        )
        try:
            async for evt in session.run_turn(text, history):
                # AgentEvent → 前端 WS 消息
                payload = {"type": evt.type, **evt.payload}
                if session_id:
                    payload.setdefault("session_id", session_id)
                try:
                    await websocket.send_json(payload)
                except Exception as e:
                    log.debug("[AI] WS send failed: %s", e)
                    break
        except Exception as e:
            log.exception("[AI] run_turn failed: %s", e)
            try:
                await websocket.send_json({"type": "error", "message": str(e)[:200]})
            except Exception:
                pass
        finally:
            session.close()

    elif msg_type == "ping":
        return  # 主循环已处理

    elif msg_type == "stop":
        # claudedemo 模式: claude 一次性 per-turn, stop 实际意义有限
        # 暂不实现: 若用户想中断, 关 WS 即可 (claude 子进程随 WS 断开被 close())
        return

    else:
        await websocket.send_json({
            "type": "error",
            "message": f"unknown agent_channel msg type: {msg_type}",
        })