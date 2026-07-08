"""
request_logging.py — FastAPI HTTP 请求/响应日志中间件（server-interaction-logging REQ-LOG-003/004/005）

行为：
- 请求进入：记 [front->svc][trace=XXX] <METHOD> <path> body=... query=... headers=...
- 响应返回：记 [front<-svc][trace=XXX] <status> <METHOD> <path> body=... (<elapsed>ms)
- 异常路径：记 ERROR [front<-svc][trace=XXX] <METHOD> <path> <exc_type>: <msg>
- 跳过 /api/health / /ws/*
- body 截断 4KB (REQ-LOG-004)
- 敏感头过滤：Authorization -> 前 8 字符 + '***'
- trace_id: 8 字符 hex (UUID v4 前缀), req/resp 配对
  - 优先用客户端传的 X-Trace-Id header
  - 否则服务端生成

v10 增修复 (trace=0ad408d4 事故):
- BaseHTTPMiddleware + await request.body() 会消耗 body 流, 下游 endpoint 拿不到
- 修复: 读 body 后, 重新构造 Request 对象, 注入 receive() 回放 body
- 这样 call_next(request) 派发的 endpoint 仍能正常解析 Pydantic 模型
"""
import json
import time
import uuid
from typing import List

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from server.utils.logflow import (
    DIR_FRONT_TO_SVC,
    DIR_SVC_TO_FRONT,
    log_interaction,
)


# 跳过日志的 path 前缀
_SKIP_PATH_PREFIXES: List[str] = [
    "/api/health",
    "/ws/",  # WS 由独立 endpoint 日志
]


# 敏感头：值需要脱敏
_SENSITIVE_HEADERS = {
    "authorization",
    "cookie",
    "x-api-key",
    "x-auth-token",
}


def _should_skip(path: str) -> bool:
    """判断是否跳过日志"""
    for prefix in _SKIP_PATH_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


def _sanitize_headers(headers) -> dict:
    """过滤敏感头"""
    out = {}
    try:
        for k, v in headers.items():
            kl = k.lower()
            if kl in _SENSITIVE_HEADERS:
                if isinstance(v, bytes):
                    v = v.decode("utf-8", errors="replace")
                vs = str(v)
                if len(vs) > 8:
                    out[k] = vs[:8] + "***"
                else:
                    out[k] = "***"
            else:
                out[k] = v if isinstance(v, str) else str(v)
    except Exception:
        return {}
    return out


async def _read_body_safe(request: Request) -> str:
    """读 body 一次（保留供后续 endpoint 使用），失败返回空串"""
    try:
        body = await request.body()
        if not body:
            return ""
        # body 转 str
        return body.decode("utf-8", errors="replace")
    except Exception:
        return ""


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """HTTP 请求/响应统一日志中间件

    用法 (server/main.py):
        from server.middleware.request_logging import RequestLoggingMiddleware
        app.add_middleware(RequestLoggingMiddleware)
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if _should_skip(path):
            return await call_next(request)

        method = request.method
        # 配对序号: 优先 X-Trace-Id header, 否则生成 8 字符 hex
        trace_id = request.headers.get("X-Trace-Id") or uuid.uuid4().hex[:8]
        request.state.trace_id = trace_id

        # 进入:记 [front->svc]
        body_str = await _read_body_safe(request)
        body_bytes = body_str.encode("utf-8") if body_str else b""
        query = dict(request.query_params)
        # 解析 body 为 dict（如可能）
        body_obj = None
        if body_str:
            try:
                if "application/json" in request.headers.get("content-type", ""):
                    body_obj = json.loads(body_str)
                else:
                    body_obj = body_str
            except Exception:
                body_obj = body_str

        log_interaction(
            DIR_FRONT_TO_SVC,
            "{} {}".format(method, path),
            data={
                "query": query,
                "body": body_obj,
                "headers": _sanitize_headers(request.headers),
            },
            level="info",
            trace_id=trace_id,
        )

        # 关键: 重新构造 Request, 注入 receive() 让下游 endpoint 能再读 body
        # (BaseHTTPMiddleware 读 body 后, 流被消耗, endpoint 的 Pydantic 解析会拿不到)
        async def receive_replay():
            return {"type": "http.request", "body": body_bytes, "more_body": False}
        request = Request(request.scope, receive_replay)

        # 业务执行 + 计时
        start = time.time()
        try:
            response: Response = await call_next(request)
        except Exception as e:
            elapsed_ms = (time.time() - start) * 1000
            log_interaction(
                DIR_SVC_TO_FRONT,
                "ERROR {} {}".format(method, path),
                data={"exc": "{}: {}".format(type(e).__name__, e)},
                elapsed_ms=elapsed_ms,
                level="error",
                trace_id=trace_id,
            )
            raise

        elapsed_ms = (time.time() - start) * 1000

        # 退出:读 response body
        resp_body_str = ""
        try:
            body_chunks = []
            async for chunk in response.body_iterator:
                body_chunks.append(chunk if isinstance(chunk, bytes) else chunk.encode("utf-8"))
            resp_body_bytes = b"".join(body_chunks)
            if resp_body_bytes:
                resp_body_str = resp_body_bytes.decode("utf-8", errors="replace")
            # 重新包装 response.body_iterator（BaseHTTPMiddleware 用完会被消费）
            from starlette.responses import Response as StarletteResponse
            response = StarletteResponse(
                content=resp_body_bytes,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )
        except Exception as e:
            resp_body_str = "<body read error: {}>".format(e)

        # 解析 response body 为 dict（如可能）
        resp_obj = None
        if resp_body_str and len(resp_body_str) < 8192:
            try:
                resp_obj = json.loads(resp_body_str)
            except Exception:
                resp_obj = resp_body_str[:1024]
        elif resp_body_str:
            resp_obj = resp_body_str[:1024] + " [truncated]"

        # 业务 4xx 视为 warning，5xx 视为 error，2xx/3xx info
        status = response.status_code
        if 500 <= status < 600:
            level = "error"
        elif 400 <= status < 500:
            level = "warning"
        else:
            level = "info"

        log_interaction(
            DIR_SVC_TO_FRONT,
            "{} {} {}".format(status, method, path),
            data={"body": resp_obj},
            elapsed_ms=elapsed_ms,
            level=level,
            trace_id=trace_id,
        )
        # 响应头加 X-Trace-Id, 客户端可拿这个配对
        response.headers["X-Trace-Id"] = trace_id
        return response
