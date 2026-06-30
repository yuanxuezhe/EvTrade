"""
push/log_helpers.py — push 交互日志 + 广播日志

REQ-LOG-003: server-interaction-logging 规范。
push 是 fire-and-forget，msg_id 来自 broker 推送（可能为空），无现成 trace_id 时用 UUID 生成。
"""
import logging
import uuid as _uuid
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)


def _log_push_interaction(func: str, wire_len: int, msg_type: str, msg_id: str) -> str:
    """记 [svc<-rpc] push 交互日志。

    Returns:
        本次 push 的 trace_id（8 字符），用于串联后续日志。
    """
    from server.utils.logflow import DIR_SVC_FROM_RPC, log_interaction

    push_trace = (msg_id or "").strip().strip("\x00").strip()[:8] or _uuid.uuid4().hex[:8]
    log_interaction(
        DIR_SVC_FROM_RPC,
        "push func={} wire_len={}".format(func, wire_len),
        data={"func": func, "wire_len": wire_len, "msg_type": msg_type},
        level="info",
        trace_id=push_trace,
    )
    return push_trace


def _log_push_broadcast(
    channel: str,
    data: Any,
    ts: str,
    func: str,
    active_trd_date: Optional[str],
    push_trace: str,
) -> Dict[str, Any]:
    """记广播日志并返回 WS payload。"""
    from server.utils.logflow import DIR_SVC_TO_FRONT, log_interaction

    payload = {
        "type": func,
        "channel": channel,
        "ts": ts,
        "data": data,
    }
    log.info(
        "RPClient.push broadcast → %s (trd_date=%s)%s",
        channel,
        active_trd_date or "?",
        ("\n" + "\n".join(
            "  " + k + " = " + repr(v)
            for k, v in sorted(data.items())
        )) if data else " (empty row)",
    )
    log_interaction(
        DIR_SVC_TO_FRONT,
        "ws broadcast channel={} (push)".format(channel),
        data={"channel": channel, "payload": payload},
        level="info",
        trace_id=push_trace,
    )
    return payload


__all__ = ["_log_push_interaction", "_log_push_broadcast"]