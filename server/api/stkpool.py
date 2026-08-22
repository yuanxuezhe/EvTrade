"""
server/api/stkpool.py — 证券池 REST 端点 (add-stkpool-module change)

端点 (前缀 /api/stkpool):
- GET    /api/stkpool                       全量主表, 按 id ASC
- POST   /api/stkpool                       创建池 (body: name, remark?)
- PUT    /api/stkpool/{pool_id}             改池名/备注 (partial update)
- DELETE /api/stkpool/{pool_id}             删池 (CASCADE 清明细)
- GET    /api/stkpool/{pool_id}/detail      池明细
- POST   /api/stkpool/{pool_id}/detail      加明细 (body: stock_code)
- DELETE /api/stkpool/{pool_id}/detail/{stock_code}  删明细

鉴权: 全部走 auth (任何登录用户), 不分 RBAC 角色 (决策 2)

错误码:
- POOL_NOT_FOUND       404 池不存在
- DETAIL_NOT_FOUND     404 明细不存在
- POOL_NAME_DUPLICATE  409 name 重复
- VALIDATION_ERROR     422 Pydantic 校验 (FastAPI 自动)
- INTERNAL_ERROR       500 DB 异常
"""
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from server.repo.stkpool import (
    StkpoolRepo,
    PoolNotFound, PoolNameDuplicate, DetailNotFound,
)


router = APIRouter()


# ============================================================
# Pydantic Schemas
# ============================================================

class StkpoolCreate(BaseModel):
    """POST /api/stkpool body"""
    name: str = Field(min_length=1, max_length=64, description='池名')
    remark: str = Field(default='', max_length=255, description='备注')


class StkpoolUpdate(BaseModel):
    """PUT /api/stkpool/{pool_id} body (partial update)"""
    name: Optional[str] = Field(default=None, min_length=1, max_length=64)
    remark: Optional[str] = Field(default=None, max_length=255)


class StkpoolDetailAdd(BaseModel):
    """POST /api/stkpool/{pool_id}/detail body

    支持批量 — stock_codes 用逗号分隔多个代码
    容量: max_length=10_000_000 (≈ 100万只股票)
    """
    stock_codes: str = Field(
        min_length=1,
        max_length=10_000_000,
        description='股票代码, 多个用英文逗号分隔 (如 "600519.SH,000001.SZ")',
    )


# ============================================================
# 端点
# ============================================================

@router.get("")
def list_pools():
    """GET /api/stkpool — 全量主表, 按 id ASC"""
    pools = StkpoolRepo.list_pools()
    return {"pools": [p.to_dict() for p in pools]}


@router.post("", status_code=201)
def create_pool(payload: StkpoolCreate):
    """POST /api/stkpool — 创建池"""
    try:
        row = StkpoolRepo.create_pool(name=payload.name, remark=payload.remark)
    except PoolNameDuplicate as e:
        raise HTTPException(status_code=409, detail=str(e))
    return row.to_dict()


@router.put("/{pool_id}")
def update_pool(pool_id: int, payload: StkpoolUpdate):
    """PUT /api/stkpool/{pool_id} — 改池名/备注"""
    try:
        row = StkpoolRepo.update_pool(
            pool_id=pool_id,
            name=payload.name,
            remark=payload.remark,
        )
    except PoolNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PoolNameDuplicate as e:
        raise HTTPException(status_code=409, detail=str(e))
    return row.to_dict()


@router.delete("/{pool_id}", status_code=204)
def delete_pool(pool_id: int):
    """DELETE /api/stkpool/{pool_id} — 删池 (CASCADE 清明细)"""
    ok = StkpoolRepo.delete_pool(pool_id)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail=f"POOL_NOT_FOUND: id={pool_id}",
        )
    return None


@router.get("/{pool_id}/detail")
def list_detail(pool_id: int):
    """GET /api/stkpool/{pool_id}/detail — 池明细"""
    try:
        details = StkpoolRepo.list_detail(pool_id)
    except PoolNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"details": [d.to_dict() for d in details]}


@router.post("/{pool_id}/detail", status_code=201)
def add_detail(pool_id: int, payload: StkpoolDetailAdd):
    """POST /api/stkpool/{pool_id}/detail — 加明细 (支持批量)

    body: {"stock_codes": "600519.SH,000001.SZ"}

    行为:
    - 后端按逗号 split + 去空 + 去重 + 校验格式
    - 逐个 INSERT IGNORE (idempotent), 不存在则插入, 重复则跳过
    - 全部成功返 201 + {added: N, skipped: M}
    """
    codes = [c.strip() for c in payload.stock_codes.split(',') if c.strip()]
    if not codes:
        raise HTTPException(
            status_code=422,
            detail="VALIDATION_ERROR: stock_codes cannot be empty after split",
        )

    # 格式校验
    import re
    pattern = re.compile(r'^\d{6}\.(SH|SZ|BJ)$')
    invalid = [c for c in codes if not pattern.match(c)]
    if invalid:
        raise HTTPException(
            status_code=422,
            detail=f"VALIDATION_ERROR: invalid stock_codes: {invalid[:5]}",
        )

    try:
        added, skipped = StkpoolRepo.add_detail_batch(pool_id, codes)
    except PoolNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"pool_id": pool_id, "added": added, "skipped": skipped}


@router.delete("/{pool_id}/detail/{stock_code}", status_code=204)
def remove_detail(pool_id: int, stock_code: str):
    """DELETE /api/stkpool/{pool_id}/detail/{stock_code} — 删明细"""
    # 先验池存在 (404 POOL_NOT_FOUND 比 404 DETAIL_NOT_FOUND 信息更准)
    import server.repo.stkpool as _repo
    if _repo.Stkpool.query_one(id=pool_id) is None:
        raise HTTPException(
            status_code=404,
            detail=f"POOL_NOT_FOUND: id={pool_id}",
        )
    ok = StkpoolRepo.remove_detail(pool_id, stock_code)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail=f"DETAIL_NOT_FOUND: id={pool_id}, stock_code='{stock_code}'",
        )
    return None
