"""
main.py — FastAPI app 入口（phase-2 拆分后）

职责：
- CORS 配置
- 启动 / 关闭 hook（DB seed / RPC client 生命周期）
- 路由注册（public / protected / admin 三组）
- /api/health
- WebSocket 端点注册（实现在 server/ws/endpoint.py）

不在此处的逻辑：
- DB seed 实现在 server/lifecycle/seed.py
- WebSocket endpoint 实现在 server/ws/endpoint.py
- 业务路由在 server/api/* 各自模块
"""
import os
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware

from server.db import SessionLocal
from server.auth.deps import get_current_user
from server.api import positions, holdings, orders, trades, asset, auth as auth_api, users as users_api
from server.api import clock, fee_config
from server.api import system as system_api  # v8: 系统级查询（active-day）
from server.api import t0_stats, t0_aggregate
from server.api.admin import sys_status as admin_sys_status, reconcile as admin_reconcile, session as admin_session
from server.rpc.client import get_rpc_client, close_rpc_client
from server.ws import register_ws_endpoint
from server.lifecycle import init_and_seed

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
app.include_router(trades.router, prefix="/api/trades", tags=["trades"], dependencies=_AUTH)
app.include_router(asset.router, prefix="/api/asset", tags=["asset"], dependencies=_AUTH)
app.include_router(fee_config.router, prefix="/api/fee-config", tags=["fee-config"], dependencies=_AUTH)
app.include_router(system_api.router, prefix="/api/system", tags=["system"], dependencies=_AUTH)  # v8


# ---- Admin routes (login required, role checked by handler) ----------------
_AUTH_ADMIN = [Depends(get_current_user)]
app.include_router(users_api.router, prefix="/api/users", tags=["users"], dependencies=_AUTH_ADMIN)
app.include_router(admin_sys_status.router, prefix="/api/admin/sys-status", tags=["admin-sys-status"], dependencies=_AUTH_ADMIN)
app.include_router(admin_reconcile.router, prefix="/api/admin/reconcile", tags=["admin-reconcile"], dependencies=_AUTH_ADMIN)
app.include_router(admin_session.router, prefix="/api/admin/trading-session", tags=["admin-session"], dependencies=_AUTH_ADMIN)


@app.get("/api/health")
def health():
    return {"status": "ok"}
