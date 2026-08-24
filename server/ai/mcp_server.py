"""
server/ai/mcp_server.py — EvTrade 内部 HTTP MCP server (claudedemo 模式)

架构 (2026-08-24):
    claude -p 子进程 → --mcp-config http://127.0.0.1:{RAND}/mcp
                       ↓ JSON-RPC over streamable-HTTP
                     本服务 (bind 127.0.0.1 随机端口)
                       ↓ tools/call
                     server.ai.tools.call(name, args)

实现要点 (来自 claudedemo/src/mcp/http.rs):
    - HTTP/1.1 单 POST /mcp, 一请求一连接, Connection: close
    - JSON-RPC 2.0 over HTTP body
    - 空 body → 202 Accepted (MCP notification)
    - initialize → 200 + Mcp-Session-Id header
    - tools/list → 200 + 工具 schema 列表
    - tools/call → 200 + 工具结果 (text 类型)
    - 解析失败 → JSON-RPC ParseError (-32700)
    - 未知 method → MethodNotFound (-32601)
    - 工具异常 → isError=True (MCP 标准错误体)

约束:
    - 仅绑 127.0.0.1, 不暴露外网 (claude 子进程同机访问)
    - 端口 0 = 操作系统分配 (用于多实例 / 测试隔离)
    - 单进程 accept loop, 每连接 1 thread (claude 一次性 HTTP 请求, 无并发压力)
    - session_id 固定字符串 (无状态 dispatch)
"""
from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .tools import TOOL_SCHEMAS, call as call_tool

log = logging.getLogger(__name__)

# JSON-RPC 2.0 错误码
PARSE_ERROR = -32700
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

# MCP 协议版本 (claude Code 2024-11-05 起, 与 claudedemo 一致)
MCP_PROTOCOL_VERSION = "2024-11-05"
SESSION_ID = "evtrade-mcp-1"


def _make_response(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _make_error(req_id, code, message):
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _tool_result_text(value):
    """工具返回的 dict 转 MCP text content."""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def dispatch(req: dict):
    """JSON-RPC request → (response_dict or None). None 表示 notification."""
    method = req.get("method", "")
    req_id = req.get("id")
    params = req.get("params") or {}

    if method == "initialize":
        return _make_response(req_id, {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "evtrade-mcp", "version": "0.1.0"},
        })

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        return _make_response(req_id, {"tools": TOOL_SCHEMAS})

    if method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments") or {}
        try:
            result = call_tool(name, args)
        except KeyError as e:
            return _make_error(req_id, METHOD_NOT_FOUND, str(e))
        except (ValueError, TypeError) as e:
            return _make_response(req_id, {
                "content": [{"type": "text", "text": _tool_result_text({"error": str(e)})}],
                "isError": True,
            })
        except Exception as e:
            log.exception("tool %s failed: %s", name, e)
            return _make_response(req_id, {
                "content": [{"type": "text", "text": _tool_result_text({"error": f"internal: {e}"})}],
                "isError": True,
            })
        return _make_response(req_id, {
            "content": [{"type": "text", "text": _tool_result_text(result)}],
            "isError": False,
        })

    return _make_error(req_id, METHOD_NOT_FOUND, f"unknown method: {method!r}")


class _MCPHandler(BaseHTTPRequestHandler):
    """单请求 / 单响应 / Connection: close. 与 claudedemo 同款."""

    def log_message(self, fmt, *args):
        log.debug("mcp http: " + fmt, *args)

    def do_POST(self):  # noqa: N802 (BaseHTTPRequestHandler API)
        path = self.path.split("?", 1)[0]
        if path not in ("/mcp", "/mcp/"):
            self._write(404, "Not Found", b"")
            return

        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length > 0 else b""

        if not body:
            self._write(202, "Accepted", b"", extra_headers=())
            return

        try:
            req = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            resp = _make_error(None, PARSE_ERROR, f"bad json: {e}")
            self._write(200, "OK", json.dumps(resp).encode("utf-8"))
            return

        if not isinstance(req, dict):
            resp = _make_error(None, INVALID_PARAMS, "request must be object")
            self._write(200, "OK", json.dumps(resp).encode("utf-8"))
            return

        result = dispatch(req)
        if result is None:
            self._write(202, "Accepted", b"", extra_headers=())
            return

        extra = ()
        if req.get("method") == "initialize":
            extra = (("Mcp-Session-Id", SESSION_ID),)

        self._write(200, "OK", json.dumps(result, ensure_ascii=False).encode("utf-8"),
                    extra_headers=extra)

    def _write(self, status_code: int, reason: str, body: bytes, extra_headers=()):
        try:
            self.send_response(status_code, reason)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            if body:
                self.send_header("Content-Type", "application/json")
            for k, v in extra_headers:
                self.send_header(k, v)
            self.end_headers()
            if body:
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass


class EvTradeMCPServer:
    """EvTrade 内部 MCP HTTP server. 绑 127.0.0.1:RAND.

    Usage:
        srv = EvTradeMCPServer.start()
        port = srv.port  # → agent_spawner 注入 claude -p 的 --mcp-config
        ...
        srv.stop()
    """

    def __init__(self, httpd: ThreadingHTTPServer, thread: threading.Thread):
        self._httpd = httpd
        self._thread = thread

    @property
    def port(self) -> int:
        return self._httpd.server_address[1]

    def stop(self):
        try:
            self._httpd.shutdown()
        except Exception:
            pass
        self._thread.join(timeout=5)

    @classmethod
    def start(cls, port: int = 0) -> "EvTradeMCPServer":
        """port=0 = OS 分配 (推荐)."""
        httpd = ThreadingHTTPServer(("127.0.0.1", port), _MCPHandler)
        thread = threading.Thread(target=httpd.serve_forever, name="evtrade-mcp", daemon=True)
        thread.start()
        log.info("[AI] MCP server started on http://127.0.0.1:%d/mcp", httpd.server_address[1])
        return cls(httpd, thread)


# ────────────────────────────────────────────────────────────────────────
# 全局单例 (FastAPI lifespan 用)
# ────────────────────────────────────────────────────────────────────────
_mcp_server: EvTradeMCPServer | None = None


def get_mcp_server() -> EvTradeMCPServer | None:
    """返回 lifespan 启动的 MCP server 实例, 未启动时 None."""
    return _mcp_server


def set_mcp_server(srv: EvTradeMCPServer | None) -> None:
    """lifespan 启动时调 set(srv), shutdown 时调 set(None)."""
    global _mcp_server
    _mcp_server = srv