"""
api/sync.py — 同步任务管理 REST 端点 (v21 stock-info-crawler)

端点:
- POST   /api/sync/stocks          启动同步任务 (admin only)
- DELETE /api/sync/stocks          停止当前同步任务 (admin only)
- GET    /api/sync/stocks/status   查当前任务状态 (admin only)

鉴权: 复用 server.auth.deps.require_admin (兄弟模块已实现)
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from server.auth.deps import require_admin
from server.services.sync.manager import sync_manager


router = APIRouter()


class StartSyncRequest(BaseModel):
    """启动同步请求 body (本次简化:无需 body,后端自动获取全市场代码列表)"""
    pass


@router.post("/stocks", status_code=202, dependencies=[Depends(require_admin)])
async def start_sync_stocks():
    """启动股票信息同步任务

    Returns:
        202 Accepted + {job_id, total}
        409 Conflict + {detail} 已有任务在跑
    """
    all_codes = await _get_all_stock_codes()
    if not all_codes:
        raise HTTPException(status_code=500, detail="no stock codes to sync")
    try:
        task = await sync_manager.start(all_codes)
        return {
            "code": 0,
            "msg": "started",
            "job_id": task.job_id,
            "total": task.counters["total"],
        }
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.delete("/stocks", dependencies=[Depends(require_admin)])
async def stop_sync_stocks():
    """停止当前同步任务"""
    stopped = await sync_manager.stop()
    if not stopped:
        raise HTTPException(status_code=404, detail="no running sync task")
    return {"code": 0, "msg": "stop requested"}


@router.get("/stocks/status", dependencies=[Depends(require_admin)])
async def get_sync_status():
    """查当前同步任务状态"""
    status = sync_manager.status()
    if status is None:
        return {"code": 0, "msg": "idle", "task": None}
    return {"code": 0, "msg": "ok", "task": status}


async def _get_all_stock_codes() -> List[str]:
    """获取全市场股票代码列表(v21 简化实现)

    策略:
    1. 从 positions 表读已持仓(真实数据)
    2. 合并全市场已知代码列表(沪深 A 股 ~5400 只)

    本次实现:从 positions 读 + 返回内置常用代码 20 只(避免一开始就爬 5400 只耗时)
    """
    try:
        from server.db import SessionLocal
        from server.models.orm import Position
        db = SessionLocal()
        try:
            rows = db.query(Position.stock_code).all()
            position_codes = [r[0] for r in rows]
        finally:
            db.close()
    except Exception:
        position_codes = []

    # v24: 优先用 sina_list 拉沪深京 A 股全市场 (~5529 只) ,
    #       合并 positions 表持仓代码 (交易过的小盘股兜底, 可能不在 sina 当前列表)
    #       builtin 兜底列表被 sina 完整覆盖 (都是大盘股, sina 必有)
    from server.crawler.sources.sina_list import fetch_all_a_codes
    try:
        sina_codes = fetch_all_a_codes(use_cache=True)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"全市场代码拉取失败 (sina_list): {exc}",
        )
    merged = set(sina_codes) | set(position_codes)
    return sorted(merged)