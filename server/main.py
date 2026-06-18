import os
from fastapi import FastAPI, Depends, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from db import init_db, SessionLocal
from models.user import User
from auth.security import hash_password, decode_token
from auth.deps import get_current_user
from api import positions, holdings, orders, trades, asset, auth as auth_api, users as users_api
from api import clock, fee_config
from api import t0_stats
from api.admin import sys_status as admin_sys_status, reconcile as admin_reconcile, session as admin_session
from ws.manager import ws_manager
from rpc.client import get_rpc_client, close_rpc_client
from config import validate_config
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


@app.on_event("startup")
def on_startup():
    """Create tables and seed default admin if no users exist."""
    # 启动时验证配置
    validate_config()
    init_db()
    db = SessionLocal()
    try:
        count = db.query(User).count()
        if count == 0:
            admin = User(
                username="admin",
                password_hash=hash_password("admin123"),
                role="admin",
                full_name="系统管理员",
                is_active=True,
                must_change_password=True,
            )
            db.add(admin)
            db.commit()
            print("[INIT] Created default admin account: admin / admin123")
            print("[INIT] Please change the password after first login.")
    finally:
        db.close()


@app.on_event("startup")
async def on_startup_rpc():
    """启动 RPC 客户端（同时启动 reply 监听 + push 监听）。"""
    try:
        await get_rpc_client()
    except Exception as e:
        print(f"[INIT] RPC client failed to start: {e}")


# 注：quote subscriber 已迁移到 hq/hqserver.py，前端 quote_update 频道直连 hqserver :8765


@app.on_event("shutdown")
async def on_shutdown_rpc():
    try:
        await close_rpc_client()
    except Exception as e:
        print(f"[SHUTDOWN] RPC client close error: {e}")


# 注：quote subscriber 关闭逻辑已迁出本 server（hqserver 自己管）


# ---- Public routes ------------------------------------------------------
app.include_router(auth_api.router, prefix="/api/auth", tags=["auth"])
app.include_router(clock.router, prefix="/api/trading", tags=["trading-clock"])


# ---- Protected routes (require login) -----------------------------------
_AUTH = [Depends(get_current_user)]

app.include_router(positions.router, prefix="/api/positions", tags=["positions"], dependencies=_AUTH)
app.include_router(holdings.router, prefix="/api/holdings", tags=["holdings"], dependencies=_AUTH)
app.include_router(orders.router, prefix="/api/orders", tags=["orders"], dependencies=_AUTH)
app.include_router(t0_stats.router, prefix="/api/orders", tags=["t0-stats"], dependencies=_AUTH)
app.include_router(trades.router, prefix="/api/trades", tags=["trades"], dependencies=_AUTH)
app.include_router(asset.router, prefix="/api/asset", tags=["asset"], dependencies=_AUTH)
app.include_router(fee_config.router, prefix="/api/fee-config", tags=["fee-config"], dependencies=_AUTH)


# ---- Admin routes (login required, role checked by handler) ----------------
_AUTH_ADMIN = [Depends(get_current_user)]
app.include_router(users_api.router, prefix="/api/users", tags=["users"], dependencies=_AUTH_ADMIN)
app.include_router(admin_sys_status.router, prefix="/api/admin/sys-status", tags=["admin-sys-status"], dependencies=_AUTH_ADMIN)
app.include_router(admin_reconcile.router, prefix="/api/admin/reconcile", tags=["admin-reconcile"], dependencies=_AUTH_ADMIN)
app.include_router(admin_session.router, prefix="/api/admin/trading-session", tags=["admin-session"], dependencies=_AUTH_ADMIN)


@app.get("/api/health")
def health():
    return {"status": "ok"}


# ---- WebSocket ----------------------------------------------------------
@app.websocket("/ws/{channel}")
async def websocket_endpoint(websocket: WebSocket, channel: str):
    """前端订阅推送。channel ∈ order_update | trade_update | position_update | asset_update。

    通过 query param ?token=JWT 认证；无 token 则拒绝连接。
    """
    token = websocket.query_params.get("token")
    if not token or not decode_token(token):
        await websocket.close(code=4001, reason="Unauthorized")
        return
    await ws_manager.connect(websocket, channel)
    try:
        # 服务端不依赖客户端消息；接收仅用于 keepalive / 触发 disconnect
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, channel)
    except Exception as e:
        print(f"[WS] error on {channel}: {e}")
        ws_manager.disconnect(websocket, channel)
