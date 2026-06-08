from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api import positions, orders, trades, asset

app = FastAPI(title="EvTrade API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(positions.router, prefix="/api/positions", tags=["positions"])
app.include_router(orders.router, prefix="/api/orders", tags=["orders"])
app.include_router(trades.router, prefix="/api/trades", tags=["trades"])
app.include_router(asset.router, prefix="/api/asset", tags=["asset"])

@app.get("/api/health")
async def health():
    return {"status": "ok"}