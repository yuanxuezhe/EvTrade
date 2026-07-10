"""
quote.py — 行情快照 REST API（2026-07-09 quote-snapshot-subscribe, 2026-07-10 quote-cache）

提供：
- GET /api/quote/snapshots  — 批量查最新快照（POST body: {stock_codes:[...]}）
- GET /api/quote/snapshot/{stock_code} — 单条查
- GET /api/quote/snapshot/{stock_code}/depth — 单条 + 5档买卖深度（供 QuotePanel.vue）

📌 2026-07-10 quote-cache：读路径改为 cache 优先，miss 时查 DB 回填到 cache
📌 数据源：内存 QuoteCache（主） + quote_snapshots 表（兜底）
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
from server.cache.quote_cache import get_quote_cache  # 2026-07-10 quote-cache
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
    """批量查 stock_codes 当前最新快照（cache 优先 + DB 回填）"""
    if not body.stock_codes:
        return SnapshotsResponse(code=0, msg="empty list", snapshots={})
    if len(body.stock_codes) > 200:
        raise HTTPException(status_code=400, detail="max 200 stock_codes per request")
    # 去重 + strip
    codes = list({c.strip() for c in body.stock_codes if c and c.strip()})
    cache = get_quote_cache()

    # 2026-07-10 quote-cache: 先读 cache, 收集 miss 的 code
    cached = cache.multi_get(codes)
    missing = [c for c in codes if c not in cached]
    snapshots: dict = {code: snap for code, snap in cached.items()}

    # 2026-07-10 quote-cache: miss 的走 DB 回填 (启动期 + 后台 flush 间隔之间的窗口)
    if missing:
        rows = repo_get_latest_multi(db, missing)
        for code, snap in rows.items():
            d = repo_to_dict(snap)
            snapshots[code] = d
            # 回填 cache（让后续读直接命中）
            cache.set(d)
        # 还没在 DB 里的（比如新股票从来没 tick 过）静默跳过

    return SnapshotsResponse(code=0, msg="", snapshots=snapshots)


@router.get("/snapshot/{stock_code}", response_model=SnapshotResponse)
async def get_snapshot(
    stock_code: str,
    db: Session = Depends(get_db),
):
    """单条 stock_code 最新快照（cache 优先 + DB 回填）"""
    cache = get_quote_cache()
    snap = cache.get(stock_code)
    if snap is not None:
        return SnapshotResponse(code=0, msg="", snapshot=snap)
    # cache miss → 查 DB 回填
    db_snap = repo_get_latest(db, stock_code)
    if not db_snap:
        return SnapshotResponse(code=404, msg=f"no snapshot for {stock_code}", snapshot=None)
    d = repo_to_dict(db_snap)
    cache.set(d)  # 回填 cache
    return SnapshotResponse(code=0, msg="", snapshot=d)