"""
api/quote_sync.py — 历史行情补全 REST 端点 (his-quote-backfill)

端点 (全部 require_admin):
- GET    /api/quote-sync              列配置 (任务表)
- POST   /api/quote-sync              新增配置行
- DELETE /api/quote-sync/{stock_code} 删配置 (不删 minute_bars 数据)
- PATCH  /api/quote-sync/{stock_code} 改 auto_sync / end_date
- POST   /api/quote-sync/sync         按日同步 {stock_code, date} → 拉当日 1m → 落库 → 成功/失败

响应 envelope: 成功 {code:0, msg, ...}; 失败 {code:非0, msg:原因}
(单日同步用 HTTP 200 + code 区分成败, 前端据 code 显示失败原因)
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from server.auth.deps import require_admin
from server.services.quote_sync import repository as repo
from server.services.quote_sync.broker import BrokerError
from server.services.quote_sync.sync import sync_one_day
from server.services.quote_sync.manager import manager

router = APIRouter()


# ─────────────── schemas ───────────────


class ConfigCreate(BaseModel):
    stock_code: str = Field(min_length=1, max_length=16)
    start_date: str = Field(pattern=r"^\d{8}$")
    end_date: str = Field(default="", max_length=8)  # 空=开放到昨天
    auto_sync: int = Field(default=1, ge=0, le=1)


class ConfigPatch(BaseModel):
    auto_sync: Optional[int] = Field(default=None, ge=0, le=1)
    end_date: Optional[str] = None


class DaySyncRequest(BaseModel):
    stock_code: str = Field(min_length=1, max_length=16)
    date: str = Field(pattern=r"^\d{8}$")


# ─────────────── 配置 CRUD ───────────────


@router.get("", dependencies=[Depends(require_admin)])
def list_configs():
    """列行情同步任务表 (全部配置行)。"""
    rows = repo.list_configs()
    return {
        "code": 0,
        "msg": "ok",
        "list": [r.to_dict() for r in rows],
        "total": len(rows),
    }


@router.post("", dependencies=[Depends(require_admin)])
def add_config(body: ConfigCreate):
    """新增配置行; last_loaded_date 自动 = MIN(昨天, 已落地最大日期, start_date)。"""
    if repo.get_config(body.stock_code) is not None:
        raise HTTPException(409, detail=f"CONFIG_EXISTS: {body.stock_code} 已有配置")
    row = repo.add_config(
        stock_code=body.stock_code,
        start_date=body.start_date,
        end_date=body.end_date,
        auto_sync=body.auto_sync,
    )
    return {"code": 0, "msg": "created", "data": row.to_dict()}


@router.delete("/{stock_code}", dependencies=[Depends(require_admin)])
def delete_config(stock_code: str):
    """删配置行 (不删 minute_bars 已落地数据)。"""
    if not repo.delete_config(stock_code):
        raise HTTPException(404, detail=f"NOT_FOUND: {stock_code} 无配置")
    return {"code": 0, "msg": "deleted"}


@router.patch("/{stock_code}", dependencies=[Depends(require_admin)])
def patch_config(stock_code: str, body: ConfigPatch):
    """改 auto_sync / end_date。"""
    if repo.get_config(stock_code) is None:
        raise HTTPException(404, detail=f"NOT_FOUND: {stock_code} 无配置")
    data = {}
    if body.auto_sync is not None:
        data["auto_sync"] = body.auto_sync
    if body.end_date is not None:
        data["end_date"] = body.end_date
    if data:
        repo.update_cfg(stock_code, data)
    return {"code": 0, "msg": "updated"}


# ─────────────── 按日同步 ───────────────


@router.post("/sync", dependencies=[Depends(require_admin)])
async def sync_day(body: DaySyncRequest):
    """按日同步: 拉 body.date 当日 1m → upsert minute_bars → 推进游标。

    成功 (含假日 0 根) → {code:0, msg, bars, last_loaded_date}
    失败 (broker 连不上/无配置) → {code:1, msg:失败原因} (游标不动)
    """
    try:
        result = await manager.sync_one_day_guarded(body.stock_code, body.date)
    except BrokerError as e:
        return {"code": 1, "msg": str(e)}
    except Exception as e:
        return {"code": 1, "msg": f"SYNC_ERROR: {e}"}
    return {
        "code": 0,
        "msg": "ok",
        "bars": result["bars"],
        "last_loaded_date": result["last_loaded_date"],
    }
