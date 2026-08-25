"""
main.py — FastAPI app 入口（phase-2 拆分后）

职责：
- CORS 配置
- 启动 / 关闭 hook（DB seed / RPC client 生命周期）
- 路由注册（public / protected / admin 三组）
- /api/health
- WebSocket 端点注册（实现在 server/ws/endpoint.py）
- root logger 显式设 INFO（server.interaction / uvicorn.* 都靠它）

不在此处的逻辑：
- DB seed 实现在 server/lifecycle/seed.py
- WebSocket endpoint 实现在 server/ws/endpoint.py
- 业务路由在 server/api/* 各自模块
"""
import logging
import os
import asyncio
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware

from server.auth.deps import get_current_user
from server.api import positions, holdings, orders, trades, asset, auth as auth_api, users as users_api
from server.api import clock, fee_config, sysconfig as sysconfig_api  # 统一配置
from server.api import system as system_api  # 系统级查询（active-day）
from server.api import t0_stats, t0_aggregate
from server.api import t0_tasks  # change t0-task-management
from server.api import script_strategy as script_strategy_api  # script-strategy change (新模块)
from server.api import quote as quote_api  # quote 查询/订阅
from server.api import stocks as stocks_api  # stock-info-crawler
from server.api import stkpool as stkpool_api  # add-stkpool-module
from server.api import sync as sync_api  # stock-info-crawler
from server.api import ai_analysis as ai_analysis_api  # AI 分析 (invest-analyst skill 集成, 同步 PoC)
from server.ai.agent_spawner import is_claude_available as _is_claude_available, claude_missing_reason as _claude_missing_reason  # /api/ai/status 公开探测 (claude CLI 缺失优雅降级)
from server.api.admin import sys_status as admin_sys_status, reconcile as admin_reconcile, session as admin_session
from server.middleware.request_logging import RequestLoggingMiddleware
from server.rpc.client import get_rpc_client, close_rpc_client
from server.ws import register_ws_endpoint
from server.lifecycle import init_and_seed
from server.config import settings
from server.services.strategy.quote_consumer import (
    get_quote_consumer, close_quote_consumer,
)

# 显式配 root logger (server-interaction-logging REQ-LOG-005)
#   uvicorn 启动时只给 uvicorn.* 配了 handler, root 默认 WARNING, INFO 被过滤
#   清掉 uvicorn 已挂的 root handler, 再 basicConfig 设 root = INFO
#   让 [front->svc] / [svc->rpc] 等自定义 logger 可见
#   Python 3.6 兼容: basicConfig 不支持 force, 手动清 handlers
#   format='%(message)s': 不带时间戳/level/logger 前缀, 时间戳和 level 由 logflow 自带 ([ts][level])
_root = logging.getLogger()
for h in list(_root.handlers):
    _root.removeHandler(h)
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
)

# REQ-LOG-006 增: 同步挂 file handler, 日志落地 logs/server-YYYYMMDD.log
#   保留 7 天; console handler 不动 (uvicorn 容器仍能看到 stderr)
from server.utils import setup_file_logging  # noqa: E402  (依赖上面的 basicConfig)
_log_dir = setup_file_logging()

# 禁用 uvicorn 原生 access log
#   重复打印 '127.0.0.1:NNNN - "GET /api/x HTTP/1.1" 200 OK' 格式
#   已被 RequestLoggingMiddleware 的 [front<-svc] 替代
logging.getLogger("uvicorn.access").disabled = True

# 注：行情订阅已解耦到 hq/hqserver.py 的内置 WebSocket 服务 (:8765)，
# 前端 quote_update 频道直连 hqserver，不再经过本 server 转发。

app = FastAPI(title="EvTrade API")

# CORS — comma-separated origins from env, default localhost
_cors_origins = [
    x.strip()
    for x in os.environ.get(
        "EVTRADE_CORS_ORIGINS",
        # 默认允许 ① vite dev (50998) ② 客户端生产构建 (3000)
        # ③ file:// 协议 (本地双击打开 examples/*.html demo 用)
        # ④ null origin (浏览器 file:// 跨协议 POST 时 Origin header = "null")
        "http://localhost:50998,http://localhost:3000,file://,null"
    ).split(",")
    if x.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# HTTP 请求/响应日志中间件（server-interaction-logging REQ-LOG-003）
#   - 记 [front->svc] 请求 + [front<-svc] 响应
#   - 跳过 /api/health / /ws/*
app.add_middleware(RequestLoggingMiddleware)


# ---- WebSocket (必须在 startup 之前注册，因为 register 用装饰器) ----
register_ws_endpoint(app)


# ---- Startup / Shutdown hooks ------------------------------------------
@app.on_event("startup")
async def on_startup_register_loop():
    """把 main event loop 注册到 ws_manager, 让 sync 线程能 schedule broadcast"""
    import asyncio
    from server.ws.manager import ws_manager as _ws
    _ws._main_loop = asyncio.get_running_loop()
    print("[INIT] ws_manager._main_loop registered")

@app.on_event("startup")
def on_startup():
    """DB 建表 + 默认账号 seed（实现见 server/lifecycle/seed.py）"""
    init_and_seed()
    # 启动时一次性加载 sysconfig 到 cache
    from server.services import sysconfig
    sysconfig.load_all()
    print(f"[INIT] sysconfig loaded: {len(sysconfig._cache)} users")

    # strategy-exec-service: stale task 清理由 strategy_exec 服务自行处理
    #  (启动时清理 progress > 5min 没更新的 task → 标 failed, EvTrade 仅做兜底)
    # 注: 原 sweep_stale_running_tasks 在 server/strategy/service.py, 已删
    # 新位置 strategy_exec/strategy_exec/data_access/strategy_task.py (Phase 2+ 实施)
    # 此处不重复扫, 仅占位日志
    try:
        # 占位: 若以后 EvTrade 想加兜底, 在此实现
        pass
    except Exception as e:
        print(f"[INIT] stale task sweep error (non-fatal): {e}")


@app.on_event("startup")
async def on_startup_rpc():
    """启动 RPC 客户端（同时启动 reply 监听 + push 监听）。"""
    # pytest 跑 TestClient 时跳过 RPC 启动 (会尝试连真 RabbitMQ, SSL hang)
    if os.environ.get("PYTEST_CURRENT_TEST"):
        print("[INIT] pytest mode: skip RPC client")
        return
    # 测试模式 (sys_config rpc_test_mode=1): 不连 RabbitMQ
    # 业务 RPC 由 mock.py 固定应答, 无需真实链路; 启动时判定一次 (离线可用)
    from server.services import sysconfig
    if bool(sysconfig.get("rpc_test_mode", 0)):
        print("[INIT] TEST_MODE (sys_config rpc_test_mode=1): skip RPC client (mock replies)")
        return
    try:
        await get_rpc_client()
        # RPC 连接建立后启动资金定时同步 + 健康监测
        from server.services.rpc_health import start_sync
        await start_sync()
    except Exception as e:
        print(f"[INIT] RPC client failed to start: {e}")


@app.on_event("shutdown")
async def on_shutdown_rpc():
    try:
        from server.services.rpc_health import stop_sync
        await stop_sync()
    except Exception as e:
        print(f"[SHUTDOWN] rpc_health stop error: {e}")
    try:
        await close_rpc_client()
    except Exception as e:
        print(f"[SHUTDOWN] RPC client close error: {e}")


@app.on_event("startup")
async def on_startup_quote_consumer():
    """启动 QuoteConsumer（无条件启动，与策略引擎解耦）。

    📌 行情 7×24 必需：Holdings/Positions/Trade 等所有页面的最新价/市值推送都靠 QuoteConsumer,
       与 STRATEGY_ENGINE_ENABLED 无关。
    📌 pytest 模式仍跳过（避免 WS 连真行情污染测试）。
    """
    if os.environ.get("PYTEST_CURRENT_TEST"):
        print("[INIT] pytest mode: skip quote consumer")
        return
    try:
        await get_quote_consumer()
    except Exception as e:
        print(f"[INIT] quote consumer failed to start: {e}")


# 启动后台 periodic flush task (quote-cache)
from server.cache.quote_cache_flusher import start_quote_cache_flusher  # noqa: E402

_quote_cache_flusher_task = None  # type: ignore[var-annotated]


@app.on_event("startup")
async def on_startup_quote_cache_flusher():
    """启动内存 quote_cache → MySQL 的周期 flush 后台 task。

    📌 tick 走 cache.set() 不再 await MySQL，
       持久化由本 task 每 60s（可配）批量回写。
    """
    global _quote_cache_flusher_task
    if os.environ.get("PYTEST_CURRENT_TEST"):
        print("[INIT] pytest mode: skip quote cache flusher")
        return
    try:
        _quote_cache_flusher_task = start_quote_cache_flusher()
    except Exception as e:
        print(f"[INIT] quote cache flusher failed to start: {e}")


@app.on_event("shutdown")
async def on_shutdown_quote_consumer():
    try:
        await close_quote_consumer()
    except Exception as e:
        print(f"[SHUTDOWN] quote consumer close error: {e}")

    # 停止 periodic flush task（task 内部 finally 会做最后 flush）
    global _quote_cache_flusher_task
    if _quote_cache_flusher_task is not None and not _quote_cache_flusher_task.done():
        _quote_cache_flusher_task.cancel()
        try:
            await _quote_cache_flusher_task
        except Exception as e:
            print(f"[SHUTDOWN] quote cache flusher cancel: {e}")


# ---- strategy_exec_service (change strategy-exec-service) ----
# signal_consumer: 订阅 strategy.exchange → 收 signal → POST /api/orders/place

@app.on_event("startup")
async def on_startup_signal_consumer():
    try:
        from server.services.strategy.signal_consumer import start_signal_consumer
        await start_signal_consumer()
    except Exception as e:
        print(f"[STARTUP] signal_consumer start failed (non-fatal): {e}")


@app.on_event("shutdown")
async def on_shutdown_signal_consumer():
    try:
        from server.services.strategy.signal_consumer import stop_signal_consumer
        await stop_signal_consumer()
    except Exception as e:
        print(f"[SHUTDOWN] signal_consumer stop error: {e}")


# ---- REQ-AUTH-IDLE-001: token session cache 后台 sweep ----
_auth_sweep_task = None  # type: ignore[var-annotated]
_ai_mcp_server = None  # 2026-08-24 重做: EvTrade AI 助手 MCP server 全局单例 (claudedemo 模式)


@app.on_event("startup")
async def on_startup_auth_sweep():
    """启动 session cache 后台 sweep 协程 (清理 10min idle 过期的 token)。

    后端重启 → cache 清零 → 所有 token 立即失效 (用户期望行为)。
    sweep 每 60s 跑一次, 控制内存增长。
    """
    global _auth_sweep_task
    if os.environ.get("PYTEST_CURRENT_TEST"):
        print("[INIT] pytest mode: skip auth session sweep")
        return
    try:
        from server.auth.session import sweep_loop
        _auth_sweep_task = asyncio.ensure_future(sweep_loop())
        print("[INIT] auth session sweep task started")
    except Exception as e:
        print(f"[INIT] auth sweep failed to start: {e}")


@app.on_event("startup")
def on_startup_ai_mcp_server():
    """2026-08-24 重做: 启动 EvTrade AI 助手 (claudedemo 模式) 的 MCP HTTP server.

    绑 127.0.0.1:RAND, spawn claude -p 子进程时通过 --mcp-config 注入此 URL.
    pytest 模式跳过 (TestClient 不发 spawn).
    """
    global _ai_mcp_server
    if os.environ.get("PYTEST_CURRENT_TEST"):
        print("[INIT] pytest mode: skip AI MCP server")
        return
    try:
        from server.ai.mcp_server import EvTradeMCPServer, set_mcp_server
        _ai_mcp_server = EvTradeMCPServer.start(port=0)
        set_mcp_server(_ai_mcp_server)
        print(f"[INIT] AI MCP server started on http://127.0.0.1:{_ai_mcp_server.port}/mcp")
    except Exception as e:
        print(f"[INIT] AI MCP server failed to start: {e}")
        _ai_mcp_server = None


@app.on_event("shutdown")
async def on_shutdown_auth_sweep():
    """停止 auth session sweep 协程。"""
    global _auth_sweep_task
    if _auth_sweep_task is not None and not _auth_sweep_task.done():
        _auth_sweep_task.cancel()
        try:
            await _auth_sweep_task
        except Exception as e:
            print(f"[SHUTDOWN] auth sweep cancel: {e}")


@app.on_event("shutdown")
def on_shutdown_ai_mcp_server():
    """停 AI MCP server."""
    global _ai_mcp_server
    if _ai_mcp_server is not None:
        try:
            _ai_mcp_server.stop()
            print("[SHUTDOWN] AI MCP server stopped")
        except Exception as e:
            print(f"[SHUTDOWN] AI MCP server stop error: {e}")
        _ai_mcp_server = None
        from server.ai.mcp_server import set_mcp_server
        set_mcp_server(None)


# ---- Public routes ------------------------------------------------------
app.include_router(auth_api.router, prefix="/api/auth", tags=["auth"])
app.include_router(clock.router, prefix="/api/trading", tags=["trading-clock"])


# ---- Protected routes (require login) -----------------------------------
_AUTH = [Depends(get_current_user)]

app.include_router(positions.router, prefix="/api/positions", tags=["positions"], dependencies=_AUTH)
app.include_router(holdings.router, prefix="/api/holdings", tags=["holdings"], dependencies=_AUTH)
app.include_router(orders.router, prefix="/api/orders", tags=["orders"], dependencies=_AUTH)
app.include_router(sysconfig_api.router, prefix="/api/sysconfig", tags=["sysconfig"], dependencies=_AUTH)
app.include_router(t0_stats.router, prefix="/api/orders", tags=["t0-stats"], dependencies=_AUTH)
app.include_router(t0_aggregate.router, prefix="/api/orders", tags=["t0-aggregate"], dependencies=_AUTH)
app.include_router(t0_tasks.router, prefix="/api/t0-tasks", tags=["t0-tasks"], dependencies=_AUTH)
app.include_router(trades.router, prefix="/api/trades", tags=["trades"], dependencies=_AUTH)
app.include_router(asset.router, prefix="/api/asset", tags=["asset"], dependencies=_AUTH)
app.include_router(fee_config.router, prefix="/api/fee-config", tags=["fee-config"], dependencies=_AUTH)
app.include_router(system_api.router, prefix="/api/system", tags=["system"], dependencies=_AUTH)
# script-strategy change (新模块): 前端编写 Python 脚本 + 回测 + 实盘
app.include_router(script_strategy_api.router, prefix="/api/script-strategy", tags=["script-strategy"], dependencies=_AUTH)
app.include_router(quote_api.router, prefix="/api/quote", tags=["quote"], dependencies=_AUTH)
# stocks 查询 + sync 管理 (stock-info-crawler)
app.include_router(stocks_api.router, prefix="/api/stocks", tags=["stocks"], dependencies=_AUTH)
app.include_router(stkpool_api.router, prefix="/api/stkpool", tags=["stkpool"], dependencies=_AUTH)  # add-stkpool-module
# sync 管理 (admin only,内联守卫避免 _AUTH_ADMIN 未定义)
app.include_router(sync_api.router, prefix="/api/sync", tags=["sync"], dependencies=[Depends(get_current_user)])
# AI 分析 (PoC: 同步调用 invest-analyst demo 脚本, 单次 60-180s)
#   前端 axios 调用: POST /api/ai/ai-analysis (baseURL=/api + router prefix=/ai + endpoint=/ai-analysis)
app.include_router(ai_analysis_api.router, prefix="/api/ai", tags=["ai-analysis"], dependencies=_AUTH)


# ---- Admin routes (login required, role checked by handler) ----------------
_AUTH_ADMIN = [Depends(get_current_user)]
app.include_router(users_api.router, prefix="/api/users", tags=["users"], dependencies=_AUTH_ADMIN)
app.include_router(admin_sys_status.router, prefix="/api/admin/sys-status", tags=["admin-sys-status"], dependencies=_AUTH_ADMIN)
app.include_router(admin_reconcile.router, prefix="/api/admin/reconcile", tags=["admin-reconcile"], dependencies=_AUTH_ADMIN)
app.include_router(admin_session.router, prefix="/api/admin/trading-session", tags=["admin-session"], dependencies=_AUTH_ADMIN)


# ---- AI Agent WS Gateway 已迁移至 /ws/agent_channel ----------------
# 2026-08-23, ai-agent-ws-reuse-channel: AI WS 复用现有 /ws/{channel} endpoint
# （与 order_update / trade_update / quote_update 共用 ws_manager + 鉴权 + idle + ping/pong）
# 服务端: server/ws/endpoint.py + server/ws/agent_handler.py
# 客户端: client/src/api/agent.js → WS_PATH = '/ws/agent_channel'


@app.get("/api/health")
def health():
    """无鉴权健康检查 - 仅用于探活 (evctl.py / k8s probe)

    前端 keepalive 用 /api/auth/heartbeat (有 token, 会触发 touch)
    """
    return {"status": "ok"}


@app.get("/api/ai/status")
def ai_status():
    """公开 - 探测 AI 助手可用性 (前端 useAgentStore 启动时调, 决定浮动按钮是否禁用).

    不鉴权: 仅返回 boolean + reason 字符串, 无业务数据泄露.

    Returns:
        available=true  → claude CLI 在 PATH, 前端可连 WS /ws/agent_channel
        available=false → claude 缺失, 前端应禁用浮动按钮 + 展示 reason
    """
    if _is_claude_available():
        return {"available": True}
    return {"available": False, "reason": _claude_missing_reason()}
