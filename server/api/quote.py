"""
quote.py — 行情快照 REST API（2026-07-09 quote-snapshot-subscribe）

提供：
- GET /api/quote/snapshots  — 批量查最新快照（POST body: {stock_codes:[...]}）
- GET /api/quote/snapshot/{stock_code} — 单条查
- GET /api/quote/snapshot/{stock_code}/depth — 单条 + 5档买卖深度（供 QuotePanel.vue）

📌 数据源：quote_snapshots 表（由 quote_consumer 后台 UPSERT 写入）
📌 latest-only 模型：每 stock_code 1 行
📌 前端订阅触发点：
   - 持仓页加载后 → POST /api/quote/snapshots {stock_codes: holdings.codes}
   - Trade.vue 输入代码触发 → GET /api/quote/snapshot/{code}/depth
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from server.db import get_db
from server.repo.quote_snapshots import (
    get_latest as repo_get_latest,
    get_latest_multi as repo_get_latest_multi,
    to_dict as repo_to_dict,
)

router = APIRouter()


class SnapshotsRequest(BaseModel):
    stock_codes: List[str] = Field(default_factory=list, max_length=200)


class SnapshotsResponse(BaseModel):
    code: int = 0
    msg: str = ""
    snapshots: dict = Field(default_factory=dict)  # {stock_code: snapshot_dict}


class SnapshotResponse(BaseModel):
    code: int = 0
    msg: str = ""
    snapshot: Optional[dict] = None


@router.post("/snapshots", response_model=SnapshotsResponse)
async def post_snapshots(
    body: SnapshotsRequest,
    db: Session = Depends(get_db),
):
    """批量查 stock_codes 当前最新快照"""
    if not body.stock_codes:
        return SnapshotsResponse(code=0, msg="empty list", snapshots={})
    if len(body.stock_codes) > 200:
        raise HTTPException(status_code=400, detail="max 200 stock_codes per request")
    # 去重 + strip
    codes = list({c.strip() for c in body.stock_codes if c and c.strip()})
    rows = repo_get_latest_multi(db, codes)
    return SnapshotsResponse(
        code=0, msg="",
        snapshots={code: repo_to_dict(snap) for code, snap in rows.items()},
    )


@router.get("/snapshot/{stock_code}", response_model=SnapshotResponse)
async def get_snapshot(
    stock_code: str,
    db: Session = Depends(get_db),
):
    """单条 stock_code 最新快照"""
    snap = repo_get_latest(db, stock_code)
    if not snap:
        return SnapshotResponse(code=404, msg=f"no snapshot for {stock_code}", snapshot=None)
    return SnapshotResponse(code=0, msg="", snapshot=repo_to_dict(snap))