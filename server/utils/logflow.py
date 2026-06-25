"""
logflow.py — 统一交互日志入口（server-interaction-logging REQ-LOG-001..006）

4 个方向标记：
  DIR_FRONT_TO_SVC  "front->svc"   前端 HTTP 请求 → server
  DIR_SVC_TO_RPC    "svc->rpc"     server 调 broker (发送 REQ)
  DIR_SVC_FROM_RPC  "svc<-rpc"     server 收到 broker 消息 (REPLY / PUSH)
  DIR_SVC_TO_FRONT  "front<-svc"   server → 前端 (HTTP 响应 / WS 广播)

日志格式：
  [2026-06-25 10:30:00.123] [<direction>] <summary> [(<elapsed_ms>ms)]
  └─ 当 data 不为空时, 缩进 2 字符换行打印

Example:
  >>> from server.utils.logflow import log_interaction, DIR_FRONT_TO_SVC
  >>> log_interaction(DIR_FRONT_TO_SVC, 'POST /api/orders/place',
  ...                 data={'body': {'stock_code': '600030.SH'}}, elapsed_ms=3.2)
  [2026-06-25 10:30:00.123] [front->svc] POST /api/orders/place (3.2ms)
    body = {"stock_code": "600030.SH"}
"""
import json
import logging
from typing import Any, Dict, Optional

from server.services.push_helpers import format_ts


# 4 个方向常量（REQ-LOG-001）
DIR_FRONT_TO_SVC = "front->svc"
DIR_SVC_TO_RPC = "svc->rpc"
DIR_SVC_FROM_RPC = "svc<-rpc"
DIR_SVC_TO_FRONT = "front<-svc"

# body 截断上限（REQ-LOG-004）
DEFAULT_MAX_BODY_BYTES = 4 * 1024   # 4KB for HTTP
DEFAULT_MAX_RPC_BYTES = 2 * 1024    # 2KB for RPC

_LOGGER_NAME = "server.interaction"
_log = logging.getLogger(_LOGGER_NAME)


def _truncate_data(data: Any, max_bytes: int) -> str:
    """把 data 序列化为字符串，超长截断

    Args:
        data: 任意可序列化对象（dict / list / str / 数字等）
        max_bytes: 上限字节数（不是字符数）

    Returns:
        截断后的字符串;总字节超限时追加 '[truncated, total=XX bytes]'
    """
    if data is None:
        return ""
    try:
        if isinstance(data, str):
            s = data
        elif isinstance(data, (dict, list)):
            s = json.dumps(data, ensure_ascii=False, default=str)
        else:
            s = str(data)
    except Exception as e:
        # 序列化失败 → 用 repr 兜底（REQ-LOG-005 不抛业务异常）
        s = "<unserializable: {}: {}>".format(type(data).__name__, e)

    if not s:
        return ""
    raw_bytes = s.encode("utf-8", errors="replace")
    if len(raw_bytes) <= max_bytes:
        return s
    # 截断到 max_bytes（按字节截，字符数可能更少）
    truncated = raw_bytes[:max_bytes].decode("utf-8", errors="replace")
    return truncated + " [truncated, total={} bytes]".format(len(raw_bytes))


def log_interaction(
    direction: str,
    summary: str,
    *,
    data: Optional[Dict[str, Any]] = None,
    elapsed_ms: Optional[float] = None,
    level: str = "info",
) -> None:
    """统一交互日志入口（REQ-LOG-001/003/004/005/006）

    Args:
        direction: 4 个方向之一（DIR_FRONT_TO_SVC 等）
        summary: 一句话描述（如 'POST /api/orders/place'）
        data: 详细信息 dict；每个 key 一行缩进打印
        elapsed_ms: 耗时（毫秒），显示在 summary 末尾
        level: 日志级别（info / warning / error / exception）

    Returns:
        None（失败安全：内部异常被吞，不影响业务）
    """
    try:
        ts = format_ts(tz='local')  # REQ-LOG-002 本地时间统一格式
        elapsed_part = " ({:.1f}ms)".format(elapsed_ms) if elapsed_ms is not None else ""
        line = "[{}] [{}] {}{}".format(ts, direction, summary, elapsed_part)
        # 拼 data 详情（缩进 2 字符）
        if data:
            for k, v in sorted(data.items()):
                v_str = _truncate_data(v, DEFAULT_MAX_BODY_BYTES)
                # 多行 v 缩进后续行
                if "\n" in v_str:
                    v_lines = v_str.split("\n")
                    line += "\n  {} = {}".format(k, v_lines[0])
                    for vl in v_lines[1:]:
                        line += "\n    {}".format(vl)
                else:
                    line += "\n  {} = {}".format(k, v_str)

        if level == "error":
            _log.error(line)
        elif level in ("warning", "warn"):
            _log.warning(line)
        elif level == "exception":
            _log.exception(line)
        else:
            _log.info(line)
    except Exception as e:
        # 失败安全：log_interaction 本身不能挂业务
        try:
            print("[log_interaction] FAILED: {!r}".format(e))
        except Exception:
            pass
