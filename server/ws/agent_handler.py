"""
server/ws/agent_handler.py — /ws/agent_channel 薄包装

接收 Vue 用户的 WS 消息 → 转 Hermes API server /v1/runs REST 调用 → 把 Hermes SSE 事件
透传回 Vue WS（事件名对齐 Hermes：run.started / message.started / tool.started /
tool.completed / run.completed / approval.required / error）。

取代旧版自研 ConfirmRegistry 拦截 + _execute_tool 自执行（已删除）：
- 高危 tool 二次确认由 Hermes API server 自身处理（tools/approval.py）
- tool 执行在 Hermes 进程内完成（通过 server.mcp.* 工具）
- EvTrade 这层只负责 JWT 鉴权 + 协议转发

参考：
- openspec/changes/2026-08-23-upgrade-agent-to-v1-runs/proposal.md
"""
from __future__ import annotations

import asyncio
import json as _json
import logging
import os
import uuid
from typing import Callable

from fastapi import WebSocket

from server.services.agent import (
    HermesServeClient,
    HermesUnreachableError,
    HermesError,
)

log = logging.getLogger(__name__)

# Hermes API server 客户端单例（连接池复用）
_hermes_client: HermesServeClient | None = None


def get_hermes_client() -> HermesServeClient:
    global _hermes_client
    if _hermes_client is None:
        _hermes_client = HermesServeClient()
    return _hermes_client


def reset_hermes_client() -> None:
    """测试用：重置单例。"""
    global _hermes_client
    _hermes_client = None


# ─── 连接建立时推送 ready ────────────────────────────────────────
async def send_agent_ready(websocket: WebSocket, user_id: int | None) -> str:
    """agent_channel 连上后立即发 ready（REQ-ARCH-008「连上后立即发」）。

    前端 AgentWSClient.connect() 以收到 ready 事件为连接成功的标志，
    在此之前**不会**发送首条 user_message。所以 ready 必须在连接建立时主动推。

    Returns:
        session_id（连接级标识）
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
    """处理 /ws/agent_channel 的业务消息。

    支持消息类型：
      - "user_message": {text, session_id?}  → 调 submit_run + 订阅 stream_events
      - "confirmation": {pending_key, choice} → 调 respond_approval
      - "stop": {}                            → 调 stop_run
      - "ping": 已被 endpoint.py 处理
    """
    msg_type = parsed.get("type")

    if msg_type == "user_message":
        text = parsed.get("text", "").strip()
        session_id = parsed.get("session_id") or f"u{user_id or 0}-{uuid.uuid4().hex[:12]}"
        if not text:
            await _send(websocket, {"type": "error", "message": "empty message"})
            return
        await _handle_user_message(
            websocket=websocket,
            user_id=user_id,
            session_id=session_id,
            user_message=text,
            last_recv_ref=last_recv_ref,
        )

    elif msg_type == "confirmation":
        pending_key = parsed.get("pending_key", "")
        choice = parsed.get("choice", "deny")
        run_id = parsed.get("run_id", "")
        if not run_id or not pending_key:
            await _send(websocket, {
                "type": "error",
                "message": "confirmation missing run_id or pending_key",
            })
            return
        hermes = get_hermes_client()
        try:
            await hermes.respond_approval(run_id=run_id, choice=choice)
        except HermesError as e:
            log.warning("respond_approval failed: %s", e)
            await _send(websocket, {"type": "error", "message": str(e)[:200]})
        except HermesUnreachableError as e:
            log.warning("hermes unreachable on approval: %s", e)
            await _send(websocket, {"type": "error", "message": "hermes unreachable"})

    elif msg_type == "stop":
        run_id = parsed.get("run_id", "")
        if not run_id:
            return
        hermes = get_hermes_client()
        try:
            await hermes.stop_run(run_id)
        except HermesError as e:
            log.warning("stop_run failed: %s", e)
        except HermesUnreachableError:
            pass

    elif msg_type == "ping":
        # ping 已被 endpoint.py 处理
        pass

    else:
        await _send(websocket, {
            "type": "error",
            "message": f"unknown agent_channel msg type: {msg_type}",
        })


# ─── 处理 user_message：启动 run + 流式推 SSE 事件 ────────────────
async def _handle_user_message(
    *,
    websocket: WebSocket,
    user_id: int | None,
    session_id: str,
    user_message: str,
    last_recv_ref: Callable[[], None] | None = None,
) -> None:
    """薄包装：submit_run + stream_events 透传给前端。

    不再做高危 tool 拦截 / ConfirmRegistry / _execute_tool：
    - 高危 tool 由 Hermes API server 内部 tools/approval.py 拦截
    - tool 执行在 Hermes 进程内通过 MCP 完成
    - EvTrade 这层只透传 Hermes SSE 事件
    """
    hermes = get_hermes_client()

    # 健康检查（Hermes API server 未起 → 友好提示）
    if not await hermes.is_reachable():
        await _send(websocket, {
            "type": "error",
            "message": "hermes API server not reachable. "
                       "Check ~/.hermes/.env API_SERVER_KEY + hermes gateway status.",
        })
        return

    # 启动 run
    try:
        run_id = await hermes.submit_run(
            input=user_message,
            session_id=session_id,
        )
    except HermesUnreachableError as e:
        log.warning("submit_run unreachable: %s", e)
        await _send(websocket, {"type": "error", "message": "hermes unreachable"})
        return
    except HermesError as e:
        log.warning("submit_run failed: %s", e)
        await _send(websocket, {"type": "error", "message": str(e)[:200]})
        return

    log.info(
        "agent run started: run=%s session=%s user=%s",
        run_id, session_id, user_id,
    )

    # 推 run.started（先于 SSE 事件；前端可立即把消息标为「agent 正在响应」）
    await _send(websocket, {
        "type": "run.started",
        "run_id": run_id,
        "session_id": session_id,
    })

    # 流式订阅 + 透传 SSE 事件给前端
    try:
        async for evt in hermes.stream_events(run_id):
            payload = _event_to_ws_payload(evt, run_id=run_id)
            await _send(websocket, payload)
            if last_recv_ref:
                last_recv_ref()
            if evt.type == "done":
                break
    except HermesUnreachableError as e:
        log.warning("stream_events unreachable: %s", e)
        await _send(websocket, {
            "type": "error",
            "message": "hermes stream disconnected",
            "run_id": run_id,
        })
    except asyncio.CancelledError:
        log.info("stream_events cancelled: run=%s", run_id)
        raise
    except Exception as e:
        log.exception("stream_events unexpected error: %s", e)
        await _send(websocket, {
            "type": "error",
            "message": str(e)[:200],
            "run_id": run_id,
        })


# ─── Hermes SSE 事件 → WS 消息透传 ─────────────────────────────────
def _event_to_ws_payload(evt, run_id: str) -> dict:
    """把 HermesEvent 转成透传给前端的 WS 消息 dict。

    字段对齐 spec/frontend §REQ-FE-537（与 Hermes SSE 同名）。
    """
    # 默认透传 raw payload + 兜底 run_id
    payload = dict(evt.raw) if evt.raw else {}
    payload["type"] = evt.type
    if "run_id" not in payload or not payload["run_id"]:
        payload["run_id"] = evt.run_id or run_id
    if evt.session_id and "session_id" not in payload:
        payload["session_id"] = evt.session_id
    if evt.message_id and "message_id" not in payload:
        payload["message_id"] = evt.message_id
    return payload


# ─── 安全推 WS 消息 ────────────────────────────────────────────────
async def _send(ws: WebSocket, payload: dict) -> None:
    """安全推 WS 消息（peer 断开不抛）"""
    try:
        await ws.send_text(_json.dumps(payload, ensure_ascii=False))
    except Exception as e:
        log.debug("WS send failed (peer disconnected?): %s", e)