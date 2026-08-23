"""
server/ws/agent_handler.py — /ws/agent_channel 业务消息处理 (2026-08-23, ai-agent-ws-reuse-channel)

AI 助手 WS handler，复用 /ws/{channel} 现有机制（鉴权 / 心跳 / idle / ws_manager），
仅替换业务消息分发逻辑。

**与 quote_update 完全独立的协议**：
- quote_update: client subscribe → server push tick (单向)
- agent_channel: client 双向 RPC（user_message / confirmation） → server 流式推 events

消息协议:
  Vue → FastAPI:
    {type: "user_message", text: "..."}
    {type: "confirmation", pending_key, confirmed}
  FastAPI → Vue:
    {type: "ready", session_id}
    {type: "text", run_id, content}
    {type: "tool_call", name, params, run_id}
    {type: "tool_result", result, run_id}
    {type: "confirmation_required", pending_key, name, params}
    {type: "agent_complete", run_id}
    {type: "error", message, run_id}

高危 tool 拦截（与 ai-agent-panel 方案一致）:
- 收到 hermes tool_call event + is_high_risk(tool_name)
- 注册 ConfirmRegistry pending → 推 confirmation_required → 等 Vue confirm
- 用户响应 → 调 MCP tool 真执行 → 推 tool_result → 调 hermes.respond_confirmation
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from typing import Awaitable, Callable

from fastapi import WebSocket

from server.mcp import TOOL_REGISTRY, is_high_risk, get_handler  # 触发 12 tool 注册
from server.services.agent import (
    HermesServeClient,
    HermesUnreachableError,
    HermesError,
    get_confirm_registry,
    ConfirmTimeoutError,
)

log = logging.getLogger(__name__)

# Hermes serve 单例（同一进程共用）
_hermes_client: HermesServeClient | None = None


def get_hermes_client() -> HermesServeClient:
    global _hermes_client
    if _hermes_client is None:
        _hermes_client = HermesServeClient()
    return _hermes_client


# ─── session_id 生成 ─────────────────────────────────────────────
# 每个 WS 连接一个 session_id（endpoint.py 里在 connect 前调一次，存 ws_manager 索引）


def _jwt_for(user_id: int) -> str:
    """生成临时 JWT 给 MCP tool → EvTrade REST 鉴权用（同 ai-agent-panel 方案）

    注：endpoint.py 已经 decode_token 过 JWT 拿 user_id；这里把 user_id 重新 encode
    成 JWT 让 MCP tool 能调 EvTrade REST。简化方案；可改为持有原始 token。
    """
    import jwt as pyjwt
    secret = os.environ.get("JWT_SECRET", "")
    algorithm = os.environ.get("JWT_ALGORITHM", "HS256")
    if not secret:
        secret = "test_secret_for_unit_test_only_32bytes!!"
    return pyjwt.encode(
        {"user_id": user_id, "sub": str(user_id), "role": "trader"},
        secret,
        algorithm=algorithm,
    )


# ─── 连接建立时推送 ready ────────────────────────────────────────
async def send_agent_ready(websocket: WebSocket, user_id: int | None) -> str:
    """agent_channel 连上后立即发 ready（REQ-ARCH-008「连上后立即发」）。

    前端 `AgentWSClient.connect()` 以收到 `ready` 事件为连接成功的标志，
    在此之前**不会**发送首条 `user_message`。所以 ready 必须在连接建立时主动推，
    不能等第一条 user_message —— 否则前后端互相等待（前端等 ready 才发首条消息、
    后端等首条消息才发 ready），首条消息永远发不出去。

    Returns:
        本次连接生成的 session_id（连接级标识；hermes run 的 run session 另生成）。
    """
    session_id = f"u{user_id or 0}-{uuid.uuid4().hex[:12]}"
    await _send(websocket, {"type": "ready", "session_id": session_id})
    return session_id


# ─── 主入口：业务消息分发 ────────────────────────────────────────
async def handle_agent_channel_message(
    websocket: WebSocket,
    parsed: dict,
    last_recv_ref: Callable[[], None] | None = None,
    user_id: int | None = None,
) -> None:
    """处理 /ws/agent_channel 的业务消息（ping/quote_update 等其他类型已被 endpoint.py 过滤）

    Args:
        websocket: 当前 WS 连接
        parsed: 解析后的 JSON dict
        last_recv_ref: 可选 — 调它可触发 last_recv 更新（idle timeout 重置）
        user_id: 当前 user id（从 endpoint.py 传进来）
    """
    msg_type = parsed.get("type")

    if msg_type == "user_message":
        text = parsed.get("text", "").strip()
        if not text:
            await _send(websocket, {"type": "error", "message": "empty message"})
            return
        await _handle_user_message(
            websocket=websocket, user_id=user_id, user_message=text,
        )

    elif msg_type == "confirmation":
        pending_key = parsed.get("pending_key", "")
        confirmed = bool(parsed.get("confirmed", False))
        registry = get_confirm_registry()
        await registry.respond(pending_key, confirmed=confirmed)

    elif msg_type == "ping":
        # ping 已被 endpoint.py 处理（return pong + session_touch），
        # 走到这里说明 channel != ping dispatch — 忽略
        pass

    else:
        await _send(websocket, {
            "type": "error",
            "message": f"unknown agent_channel msg type: {msg_type}",
        })


# ─── 处理 user_message: 启动 hermes run + 流式推 WS events ──────
async def _handle_user_message(
    *,
    websocket: WebSocket,
    user_id: int | None,
    user_message: str,
) -> None:
    """启动 hermes run → 流式处理 events → 推 WS 给前端"""
    hermes = get_hermes_client()

    # 健康检查（hermes serve daemon 未起 → 友好提示）
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

    # session_id 单 run 唯一（hermes run 标识）。
    # ready 已在连接建立时由 endpoint.py 通过 send_agent_ready 推过
    # （REQ-ARCH-008「连上后立即发」），这里不再重复发。
    session_id = f"u{user_id or 0}-{uuid.uuid4().hex[:12]}"

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
    jwt_token = _jwt_for(user_id) if user_id else ""
    async for evt in iter_:
        if evt.type == "step_start":
            await _send(websocket, {"type": "step_start", "run_id": evt.run_id})

        elif evt.type == "text":
            await _send(websocket, {
                "type": "text",
                "run_id": evt.run_id,
                "content": evt.content,
            })

        elif evt.type == "tool_call":
            await _send(websocket, {
                "type": "tool_call",
                "name": evt.tool_name,
                "params": evt.tool_params,
                "run_id": evt.run_id,
            })
            # 高危 tool 拦截
            if is_high_risk(evt.tool_name):
                await _intercept_high_risk_tool(
                    websocket=websocket,
                    run_id=evt.run_id or run_id,
                    tool_call_id=evt.tool_call_id,
                    tool_name=evt.tool_name,
                    tool_params=evt.tool_params,
                    jwt_token=jwt_token,
                )
            else:
                # 低危 tool 直接执行
                result = await _execute_tool(
                    tool_name=evt.tool_name,
                    tool_params=evt.tool_params,
                    jwt_token=jwt_token,
                )
                await _send(websocket, {
                    "type": "tool_result",
                    "result": result,
                    "run_id": evt.run_id,
                })

        elif evt.type == "tool_result":
            await _send(websocket, {
                "type": "tool_result",
                "result": evt.tool_result,
                "run_id": evt.run_id,
            })

        elif evt.type == "confirmation_required":
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


# ─── 高危 tool 拦截 ─────────────────────────────────────────────
async def _intercept_high_risk_tool(
    *,
    websocket: WebSocket,
    run_id: str,
    tool_call_id: str,
    tool_name: str,
    tool_params: dict,
    jwt_token: str,
) -> None:
    """拦截高危 tool: 注册 pending → 等用户确认 → 调 MCP tool → 推 result"""
    registry = get_confirm_registry()
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

    await _send(websocket, {
        "type": "confirmation_required",
        "pending_key": pending_key,
        "name": tool_name,
        "params": tool_params,
    })

    async def _wait_and_execute():
        hermes = get_hermes_client()
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
        # 用户确认 → 真正执行
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

    # 创建后台 task（不阻塞主消息循环）
    asyncio.create_task(_wait_and_execute())


async def _execute_tool(
    *,
    tool_name: str,
    tool_params: dict,
    jwt_token: str,
) -> dict:
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


async def _send(ws: WebSocket, payload: dict) -> None:
    """安全推 WS 消息"""
    import json as _json
    try:
        await ws.send_text(_json.dumps(payload, ensure_ascii=False))
    except Exception as e:
        log.debug("WS send failed (peer disconnected?): %s", e)