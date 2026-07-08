"""
main.py — FastAPI app 入口（phase-2 拆分后）

职责：
- CORS 配置
- 启动 / 关闭 hook（DB seed / RPC client 生命周期）
- 路由注册（public / protected / admin 三组）
- /api/health
- WebSocket 端点注册（实现在 server/ws/endpoint.py）
- v10 增：root logger 显式设 INFO（server.interaction / uvicorn.* 都靠它）

不在此处的逻辑：
- DB seed 实现在 server/lifecycle/seed.py
- WebSocket endpoint 实现在 server/ws/endpoint.py
- 业务路由在 server/api/* 各自模块
"""
import logging
import os
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware

from server.db import SessionLocal
from server.auth.deps import get_current_user
from server.api import positions, holdings, orders, trades, asset, auth as auth_api, users as users_api
from server.api import clock, fee_config
from server.api import system as system_api  # v8: 系统级查询（active-day）
from server.api import t0_stats, t0_aggregate
from server.api import t0_tasks  # v18 change t0-task-management
from server.api import strategy as strategy_api  # change strategy_trade task 9
from server.api.admin import sys_status as admin_sys_status, reconcile as admin_reconcile, session as admin_session
from server.middleware.request_logging import RequestLoggingMiddleware
from server.rpc.client import get_rpc_client, close_rpc_client
from server.ws import register_ws_endpoint
from server.lifecycle import init_and_seed
from server.config import settings
from server.services.strategy.quote_consumer import (
    get_quote_consumer, close_quote_consumer,
)

# v10 增: 显式配 root logger (server-interaction-logging REQ-LOG-005)
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

# v10 增: 禁用 uvicorn 原生 access log
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
        "EVTRADE_CORS_ORIGINS", "http://localhost:50998"
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
def on_startup():
    """DB 建表 + 默认账号 seed（实现见 server/lifecycle/seed.py）"""
    init_and_seed()


@app.on_event("startup")
async def on_startup_rpc():
    """启动 RPC 客户端（同时启动 reply 监听 + push 监听）。"""
    try:
        await get_rpc_client()
    except Exception as e:
        print(f"[INIT] RPC client failed to start: {e}")


@app.on_event("shutdown")
async def on_shutdown_rpc():
    try:
        await close_rpc_client()
    except Exception as e:
        print(f"[SHUTDOWN] RPC client close error: {e}")


@app.on_event("startup")
async def on_startup_quote_consumer():
    """启动 QuoteConsumer（受 STRATEGY_ENGINE_ENABLED 控制）。"""
    if not settings.STRATEGY_ENGINE_ENABLED:
        print("[INIT] STRATEGY_ENGINE_ENABLED=false, quote consumer not started")
        return
    try:
        await get_quote_consumer()
    except Exception as e:
        print(f"[INIT] quote consumer failed to start: {e}")


@app.on_event("shutdown")
async def on_shutdown_quote_consumer():
    try:
        await close_quote_consumer()
    except Exception as e:
        print(f"[SHUTDOWN] quote consumer close error: {e}")


# ---- Public routes ------------------------------------------------------
app.include_router(auth_api.router, prefix="/api/auth", tags=["auth"])
app.include_router(clock.router, prefix="/api/trading", tags=["trading-clock"])


# ---- Protected routes (require login) -----------------------------------
_AUTH = [Depends(get_current_user)]

app.include_router(positions.router, prefix="/api/positions", tags=["positions"], dependencies=_AUTH)
app.include_router(holdings.router, prefix="/api/holdings", tags=["holdings"], dependencies=_AUTH)
app.include_router(orders.router, prefix="/api/orders", tags=["orders"], dependencies=_AUTH)
app.include_router(t0_stats.router, prefix="/api/orders", tags=["t0-stats"], dependencies=_AUTH)
app.include_router(t0_aggregate.router, prefix="/api/orders", tags=["t0-aggregate"], dependencies=_AUTH)
app.include_router(t0_tasks.router, prefix="/api/t0-tasks", tags=["t0-tasks"], dependencies=_AUTH)  # v18
app.include_router(trades.router, prefix="/api/trades", tags=["trades"], dependencies=_AUTH)
app.include_router(asset.router, prefix="/api/asset", tags=["asset"], dependencies=_AUTH)
app.include_router(fee_config.router, prefix="/api/fee-config", tags=["fee-config"], dependencies=_AUTH)
app.include_router(system_api.router, prefix="/api/system", tags=["system"], dependencies=_AUTH)  # v8
# strategy REST（change strategy_trade task 9）— 端点内部 _require_engine_enabled 灰度门
app.include_router(strategy_api.router, dependencies=_AUTH)


# ---- Admin routes (login required, role checked by handler) ----------------
_AUTH_ADMIN = [Depends(get_current_user)]
app.include_router(users_api.router, prefix="/api/users", tags=["users"], dependencies=_AUTH_ADMIN)
app.include_router(admin_sys_status.router, prefix="/api/admin/sys-status", tags=["admin-sys-status"], dependencies=_AUTH_ADMIN)
app.include_router(admin_reconcile.router, prefix="/api/admin/reconcile", tags=["admin-reconcile"], dependencies=_AUTH_ADMIN)
app.include_router(admin_session.router, prefix="/api/admin/trading-session", tags=["admin-session"], dependencies=_AUTH_ADMIN)


@app.get("/api/health")
def health():
    return {"status": "ok"}
