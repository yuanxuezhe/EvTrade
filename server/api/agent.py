"""
server/api/agent.py — FastAPI WebSocket Gateway: Vue ↔ Hermes serve

WS 端点：`/api/agent/ws?token=<jwt>`

握手 → JWT 校验 → 创建 session_id
接收 Vue 消息：
  - {type: "user_message", text: "..."}  → 启动 hermes run → 流式推 WS events
  - {type: "confirmation", pending_key, confirmed}  → 调 ConfirmRegistry.respond
  - {type: "ping"}  → 推 {type: "pong"}

推 Vue 消息：
  - {type: "ready", session_id}
  - {type: "step_start"}
  - {type: "text", content}
  - {type: "tool_call", name, params}
  - {type: "tool_result", result}
  - {type: "confirmation_required", pending_key, run_id, tool_call_id, name, params}
  - {type: "agent_complete"}
  - {type: "error", message}

高危 tool 拦截：
- WS gateway 收到 hermes event type='tool_call' + is_high_risk(tool_name)
- 不调 MCP tool，改为：注册 pending → 推 confirmation_required → 等 Vue confirm
- 用户确认后：调 MCP tool → 推 WS tool_result → 调 hermes respond_confirmation → 继续 run

REQ-ARCH-008（详见 openspec/specs/server-architecture/spec.md §REQ-ARCH-008）
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from typing import Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

# 触发 12 tool 注册副作用
import server.mcp  # noqa: F401
from server.mcp import TOOL_REGISTRY, is_high_risk, get_handler
from server.mcp._jwt import decode_user_id, JWTError
from server.services.agent import HermesServeClient, HermesUnreachableError, HermesError
from server.services.agent import ConfirmRegistry, get_confirm_registry, ConfirmTimeoutError

log = logging.getLogger(__name__)

router = APIRouter()

# 单例 Hermes 客户端（FastAPI 启动时复用）
_hermes_client: Optional[HermesServeClient] = None


def get_hermes_client() -> HermesServeClient:
    global _hermes_client
    if _hermes_client is None:
        _hermes_client = HermesServeClient()
    return _hermes_client


# ─── WS 端点 ─────────────────────────────────────────────────────
@router.websocket("/ws")
async def agent_ws(
    websocket: WebSocket,
    token: str = Query(..., description="用户 JWT"),
):
    """主 WS 端点 — Vue ↔ Hermes bridge"""
    # ── 1. JWT 校验（握手时） ────────────────────────────────
    try:
        user_id = decode_user_id(token)
    except JWTError as e:
        log.warning("agent WS JWT failed: %s", e)
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="invalid jwt")
        return

    await websocket.accept()
    session_id = f"u{user_id}-{uuid.uuid4().hex[:12]}"
    log.info("agent WS connected: session=%s user=%s", session_id, user_id)

    # ── 2. 启动 ConfirmRegistry cleanup（懒启动） ────────────
    registry = get_confirm_registry()
    await registry.start_cleanup_task()

    # ── 3. 推 ready ──────────────────────────────────────────
    await _send(websocket, {"type": "ready", "session_id": session_id})

    # ── 4. 主循环：双向消息分发 ──────────────────────────────
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await _send(websocket, {"type": "error", "message": "invalid JSON"})
                continue
            msg_type = msg.get("type")
            if msg_type == "user_message":
                asyncio.create_task(_handle_user_message(
                    websocket=websocket,
                    registry=registry,
                    user_id=user_id,
                    session_id=session_id,
                    user_message=msg.get("text", ""),
                ))
            elif msg_type == "confirmation":
                pending_key = msg.get("pending_key", "")
                confirmed = bool(msg.get("confirmed", False))
                await registry.respond(pending_key, confirmed=confirmed)
            elif msg_type == "ping":
                await _send(websocket, {"type": "pong"})
            else:
                await _send(websocket, {"type": "error", "message": f"unknown type: {msg_type}"})
    except WebSocketDisconnect:
        log.info("agent WS disconnected: session=%s", session_id)
    except Exception as e:
        log.exception("agent WS fatal: session=%s err=%s", session_id, e)
        try:
            await _send(websocket, {"type": "error", "message": str(e)[:200]})
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        except Exception:
            pass


# ─── 内部：处理 user_message ────────────────────────────────────
async def _handle_user_message(
    *,
    websocket: WebSocket,
    registry: ConfirmRegistry,
    user_id: int,
    session_id: str,
    user_message: str,
) -> None:
    """处理用户消息：启动 hermes run → 流式推 WS events → 拦截高危 tool."""
    if not user_message.strip():
        await _send(websocket, {"type": "error", "message": "empty message"})
        return

    hermes = get_hermes_client()

    # Hermes serve 健康检查（daemon 未起 → 友好提示）
    if not await hermes.is_reachable():
        await _send(websocket, {
            "type": "error",
            "message": "hermes serve daemon not reachable. Start it with: hermes serve",
        })
        await _send(websocket, {"type": "agent_complete"})
        return

    # 注入 12 tool（来自 server.mcp）
    tools = [
        {"name": td["name"], "description": td["description"], "schema": td["schema"]}
        for td in TOOL_REGISTRY.values()
    ]

    # 启动 run + 订阅事件
    try:
        run_id, iter_ = await hermes.run_and_subscribe(
            session_id=session_id,
            user_message=user_message,
            tools=tools,
        )
    except (HermesUnreachableError, HermesError) as e:
        await _send(websocket, {"type": "error", "message": str(e)[:200]})
        await _send(websocket, {"type": "agent_complete"})
        return

    log.info("agent run started: run=%s session=%s user=%s", run_id, session_id, user_id)

    # 流式处理 hermes events
    async for evt in iter_:
        if evt.type == "step_start":
            await _send(websocket, {"type": "step_start", "run_id": evt.run_id})

        elif evt.type == "text":
            await _send(websocket, {
                "type": "text",
                "content": evt.content,
                "run_id": evt.run_id,
            })

        elif evt.type == "tool_call":
            await _send(websocket, {
                "type": "tool_call",
                "name": evt.tool_name,
                "params": evt.tool_params,
                "run_id": evt.run_id,
            })
            # ⚠️ 高危 tool 拦截：注册 pending + 等用户确认
            if is_high_risk(evt.tool_name):
                await _intercept_high_risk_tool(
                    websocket=websocket,
                    registry=registry,
                    hermes=hermes,
                    run_id=evt.run_id or run_id,
                    tool_call_id=evt.tool_call_id,
                    tool_name=evt.tool_name,
                    tool_params=evt.tool_params,
                    jwt_token=_jwt_for(user_id),
                )
            else:
                # 低危 tool：直接执行 → 推 result
                await _execute_and_respond(
                    websocket=websocket,
                    hermes=hermes,
                    run_id=evt.run_id or run_id,
                    tool_call_id=evt.tool_call_id,
                    tool_name=evt.tool_name,
                    tool_params=evt.tool_params,
                    jwt_token=_jwt_for(user_id),
                )

        elif evt.type == "tool_result":
            await _send(websocket, {
                "type": "tool_result",
                "result": evt.tool_result,
                "run_id": evt.run_id,
            })

        elif evt.type == "confirmation_required":
            # hermes 自己要求确认（不是我们的高危拦截）→ 透传给 Vue
            await _send(websocket, {
                "type": "confirmation_required",
                "run_id": evt.run_id,
                "tool_call_id": evt.tool_call_id,
                "name": evt.tool_name,
                "params": evt.tool_params,
            })

        elif evt.type == "step_complete":
            await _send(websocket, {"type": "step_complete", "run_id": evt.run_id})

        elif evt.type == "agent_complete":
            await _send(websocket, {"type": "agent_complete", "run_id": evt.run_id})
            break

        elif evt.type == "error":
            await _send(websocket, {
                "type": "error",
                "message": evt.error_message or "hermes error",
                "run_id": evt.run_id,
            })
            # 不 break — 让 hermes 决定是否继续


# ─── 高危 tool 拦截 ─────────────────────────────────────────────
async def _intercept_high_risk_tool(
    *,
    websocket: WebSocket,
    registry: ConfirmRegistry,
    hermes: HermesServeClient,
    run_id: str,
    tool_call_id: str,
    tool_name: str,
    tool_params: dict,
    jwt_token: str,
) -> None:
    """拦截高危 tool call：注册 pending → 等用户确认 → 调 MCP → 响应 hermes."""
    # 1. 注册 pending（拿 pending_key）
    try:
        pending_key = await registry.register(
            run_id=run_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            tool_params=tool_params,
        )
    except Exception as e:
        log.exception("register pending failed: %s", e)
        await _send(websocket, {"type": "error", "message": "register pending failed"})
        return

    # 2. 推 Vue confirmation_required
    await _send(websocket, {
        "type": "confirmation_required",
        "pending_key": pending_key,
        "run_id": run_id,
        "tool_call_id": tool_call_id,
        "name": tool_name,
        "params": tool_params,
    })

    # 3. 等 Vue 确认（异步 — 不阻塞主循环，因为主循环在另一 task 跑）
    async def _wait_and_execute():
        try:
            confirmed = await registry.await_confirmation(pending_key)
        except ConfirmTimeoutError:
            log.warning("confirmation timeout: %s", pending_key)
            await _send(websocket, {
                "type": "error",
                "message": f"confirmation timeout for {tool_name}",
            })
            await hermes.respond_confirmation(
                run_id=run_id, tool_call_id=tool_call_id, confirmed=False,
            )
            return
        if not confirmed:
            await hermes.respond_confirmation(
                run_id=run_id, tool_call_id=tool_call_id, confirmed=False,
            )
            await _send(websocket, {
                "type": "tool_result",
                "result": {"ok": False, "status": "user_rejected"},
                "run_id": run_id,
            })
            return
        # 用户确认 → 执行 tool + 响应 hermes
        result = await _execute_tool(
            tool_name=tool_name, tool_params=tool_params, jwt_token=jwt_token,
        )
        await _send(websocket, {
            "type": "tool_result",
            "result": result,
            "run_id": run_id,
        })
        await hermes.respond_confirmation(
            run_id=run_id, tool_call_id=tool_call_id, confirmed=True,
        )

    asyncio.create_task(_wait_and_execute())


async def _execute_and_respond(
    *,
    websocket: WebSocket,
    hermes: HermesServeClient,
    run_id: str,
    tool_call_id: str,
    tool_name: str,
    tool_params: dict,
    jwt_token: str,
) -> None:
    """低危 tool：直接执行 + 推 Vue result + hermes 自动接收（无需 respond）"""
    result = await _execute_tool(
        tool_name=tool_name, tool_params=tool_params, jwt_token=jwt_token,
    )
    await _send(websocket, {
        "type": "tool_result",
        "result": result,
        "run_id": run_id,
    })
    # hermes 端通过 tool_result 事件自动接收 tool output（无需 RPC 响应）


async def _execute_tool(
    *,
    tool_name: str,
    tool_params: dict,
    jwt_token: str,
) -> dict:
    """执行 MCP tool（含 jwt_token 注入）"""
    handler = get_handler(tool_name)
    if handler is None:
        return {"ok": False, "error": f"unknown tool: {tool_name}", "status_code": 404}
    try:
        return await handler(jwt_token=jwt_token, **tool_params)
    except TypeError as e:
        return {"ok": False, "error": f"tool param mismatch: {e}", "status_code": 422}
    except Exception as e:
        log.exception("tool execution failed: %s", tool_name)
        return {"ok": False, "error": str(e)[:200], "status_code": 500}


# ─── helpers ─────────────────────────────────────────────────────
async def _send(ws: WebSocket, payload: dict) -> None:
    """安全推 WS 消息（捕获异常不抛）"""
    try:
        await ws.send_text(json.dumps(payload, ensure_ascii=False))
    except Exception as e:
        log.debug("WS send failed (peer disconnected?): %s", e)


# ─── JWT 注入 helper ─────────────────────────────────────────────
# 注意：mcp tool 需要 jwt_token 才能调 EvTrade REST。
# 这里我们把 user_id 反向 encode 成最小 JWT（HS256 + JWT_SECRET），
# 实际生产应该是 FastAPI 启动时持有当前 session 的真 JWT（避免二次 encode）。
# 当前简化：每次 user_message 处理时临时 encode（30s TTL）。
_jwt_cache: dict[int, tuple[str, float]] = {}
_JWT_TTL = 30.0


def _jwt_for(user_id: int) -> str:
    """生成临时 JWT（含 user_id）用于 mcp tool → EvTrade REST 鉴权"""
    now = asyncio.get_event_loop().time()
    cached = _jwt_cache.get(user_id)
    if cached and (now - cached[1]) < _JWT_TTL:
        return cached[0]
    import jwt as pyjwt
    secret = os.environ.get("JWT_SECRET", "")
    algorithm = os.environ.get("JWT_ALGORITHM", "HS256")
    if not secret:
        # 兜底：测试用 secret（仅当 JWT_SECRET 未设时）
        secret = "test_secret_for_unit_test_only_32bytes!!"
    token = pyjwt.encode(
        {"user_id": user_id, "sub": str(user_id), "role": "trader"},
        secret,
        algorithm=algorithm,
    )
    _jwt_cache[user_id] = (token, now)
    return token
