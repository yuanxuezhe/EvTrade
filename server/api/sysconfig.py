"""
api/sysconfig.py — 统一配置 CRUD (v78)

端点:
- GET    /api/sysconfig                  列出配置 (admin 看全部, 普通用户看自己的 + 继承的默认)
- GET    /api/sysconfig/{cfg_key}        读单个 (user 优先回退默认)
- POST   /api/sysconfig                  新增/upsert (普通用户只能写自己的 user, admin 可写 user='0')
- PUT    /api/sysconfig/{cfg_key}        更新 (同上)
- DELETE /api/sysconfig/{cfg_key}        删除 (admin 可删任意, 普通用户只能删自己的)
"""
import logging
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from server.auth.deps import get_current_user
from server.db import get_db
from server.models.user import User
from server.services.guards import require_admin
from server.services import sysconfig

log = logging.getLogger(__name__)

router = APIRouter()


class SysConfigOut(BaseModel):
    user: str
    cfg_key: str
    cfg_val: str
    desc: Optional[str] = ""
    has_override: Optional[bool] = False
    inherited: Optional[bool] = False
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None

    class Config:
        from_attributes = True


class SysConfigUpsert(BaseModel):
    cfg_key: str = Field(..., max_length=64)
    cfg_val: str = Field(..., max_length=512)
    desc: Optional[str] = Field("", max_length=255)
    user: Optional[str] = Field(None, description="admin 可指定 user='0' 写默认, 不传 = 写自己")


@router.get("", response_model=List[SysConfigOut])
def list_configs(
    user: Optional[str] = Query(None, description="admin 可指定用户查看; 默认看自己+默认"),
    current: User = Depends(get_current_user),
):
    """列出配置 — 普通用户看自己 + 默认; admin 可指定 user"""
    target_user = user if (current.role == "admin" and user is not None) else current.username
    rows = sysconfig.list_all(user=target_user)
    return [
        SysConfigOut(
            user=r["user"],
            cfg_key=r["cfg_key"],
            cfg_val=r["cfg_val"],
            desc="",
            has_override=r.get("has_override", False),
            inherited=r.get("inherited", False),
        )
        for r in rows
    ]


@router.get("/{cfg_key}", response_model=SysConfigOut)
def get_config(
    cfg_key: str,
    user: Optional[str] = Query(None),
    current: User = Depends(get_current_user),
):
    """读单个配置 — user 优先, 缺失回退默认"""
    target_user = user if user is not None else current.username
    val = sysconfig.get_raw(cfg_key, user=target_user)
    if val is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "msg": f"config {cfg_key} not found"})
    is_inherited = target_user != "0" and cfg_key not in sysconfig._cache.get(target_user, {})
    return SysConfigOut(
        user="0" if is_inherited else target_user,
        cfg_key=cfg_key,
        cfg_val=val,
        inherited=is_inherited,
    )


@router.post("", response_model=SysConfigOut, status_code=201)
def upsert_config(
    body: SysConfigUpsert,
    current: User = Depends(get_current_user),
):
    """新增或更新配置 — 普通用户只能写自己的; admin 可写 user='0'"""
    target_user = body.user if body.user is not None else current.username
    if target_user == "0" and current.role != "admin":
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "msg": "only admin can write user='0' defaults"})
    if target_user != "0" and target_user != current.username and current.role != "admin":
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "msg": "cannot write other user's config"})

    sysconfig.set_value(
        user=target_user,
        key=body.cfg_key,
        val=body.cfg_val,
        desc=body.desc or "",
        updated_by=current.username,
    )
    return SysConfigOut(user=target_user, cfg_key=body.cfg_key, cfg_val=body.cfg_val, desc=body.desc or "")


@router.put("/{cfg_key}", response_model=SysConfigOut)
def update_config(
    cfg_key: str,
    body: SysConfigUpsert,
    user: Optional[str] = Query(None),
    current: User = Depends(get_current_user),
):
    """更新配置 — 同 upsert 权限"""
    target_user = user if user is not None else current.username
    if target_user == "0" and current.role != "admin":
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "msg": "only admin can update user='0' defaults"})
    if target_user != "0" and target_user != current.username and current.role != "admin":
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "msg": "cannot update other user's config"})

    sysconfig.set_value(
        user=target_user,
        key=cfg_key,
        val=body.cfg_val,
        desc=body.desc or "",
        updated_by=current.username,
    )
    return SysConfigOut(user=target_user, cfg_key=cfg_key, cfg_val=body.cfg_val, desc=body.desc or "")


@router.delete("/{cfg_key}", status_code=204)
def delete_config(
    cfg_key: str,
    user: Optional[str] = Query(None),
    current: User = Depends(get_current_user),
):
    """删除配置 — admin 可删任意, 普通用户只能删自己的 (不能删默认)"""
    target_user = user if user is not None else current.username
    if target_user == "0" and current.role != "admin":
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "msg": "only admin can delete user='0' defaults"})
    if target_user != "0" and target_user != current.username and current.role != "admin":
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "msg": "cannot delete other user's config"})
    ok = sysconfig.delete_value(user=target_user, key=cfg_key)
    if not ok:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "msg": f"{target_user}/{cfg_key} not found"})
    return