"""
server/mcp/_client.py — EvTrade REST API 异步客户端 (evtrade-mcp 内部)

所有 tool 通过此 client 调 EvTrade REST API。集中管 base_url + JWT 注入 + 错误处理。
"""
import os
import logging
from typing import Any, Optional

import httpx

from ._jwt import auth_headers

log = logging.getLogger(__name__)

EVTRADE_BASE_URL = os.environ.get("EVTRADE_BASE_URL", "http://127.0.0.1:8000")
HTTP_TIMEOUT = float(os.environ.get("EVMCP_HTTP_TIMEOUT", "30.0"))


class EvTradeAPIError(Exception):
    """调 EvTrade REST API 失败 — tool 应捕获并包装成 tool result"""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"EvTrade API {status_code}: {detail}")


async def call_evtrade(
    *,
    method: str,
    path: str,
    jwt_token: str,
    params: Optional[dict[str, Any]] = None,
    json_body: Optional[dict[str, Any]] = None,
    timeout: float = HTTP_TIMEOUT,
) -> dict[str, Any]:
    """
    调 EvTrade REST API 并返 JSON dict。

    Args:
        method: GET / POST / PUT / DELETE
        path: e.g. "/api/positions"（不带 base_url）
        jwt_token: 当前用户 JWT (从 tool 参数透传)
        params: query params
        json_body: request body
        timeout: seconds (默认 30s)

    Raises:
        EvTradeAPIError: 非 2xx 响应
        httpx.RequestError: 网络异常（连接拒绝、超时等）
    """
    url = f"{EVTRADE_BASE_URL}{path}"
    headers = auth_headers(jwt_token)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.request(
                method, url, headers=headers, params=params, json=json_body
            )
        except httpx.RequestError as e:
            log.error("EvTrade API request error: %s %s: %s", method, url, e)
            raise
    if resp.status_code >= 400:
        # 尝试解析 EvTrade 标准的 {code, msg, list} 错误响应
        try:
            err = resp.json()
            detail = err.get("msg") or err.get("detail") or str(err)
        except Exception:
            detail = resp.text or "(empty)"
        log.warning("EvTrade API error: %s %s -> %s: %s", method, url, resp.status_code, detail)
        raise EvTradeAPIError(resp.status_code, detail)
    # 204 / 空 body 兜底
    if not resp.content:
        return {}
    try:
        return resp.json()
    except Exception as e:
        log.error("EvTrade API non-JSON response: %s %s: %s", method, url, e)
        raise EvTradeAPIError(resp.status_code, f"non-JSON response: {e}") from e
