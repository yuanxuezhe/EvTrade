"""
system.py — 系统级查询接口（v8 新增）

GET /api/system/active-day
  返回当前激活交易日。返回标准 RPC 格式 {code, msg, list}：
    list[0] = {trd_date, status}
  用途：前端 holdings 缓存需要权威的"当前交易日"用于推送守门
        （broker 推送带 trd_date 时,只接受与激活日匹配的记录）
        避免：前一交易日未平委托的状态变更被错误应用到今天的缓存

依赖：services.guards.resolve_active_trd_date（已存在）
"""
from fastapi import APIRouter, Depends
from db import SessionLocal
from services.guards import resolve_active_trd_date
from auth.deps import get_current_user
from models.user import User

router = APIRouter()


@router.get("/active-day")
async def get_active_day(user: User = Depends(get_current_user)):
    """当前激活交易日（标准 RPC 格式）

    Returns:
        {code: 0, msg: "", list: [{trd_date, status}]}   激活日存在
        {code: 0, msg: "", list: []}                       未做日初
        {code: 1, msg: "..."}                              异常
    """
    db = SessionLocal()
    try:
        trd_date = resolve_active_trd_date(db)
    finally:
        db.close()

    if trd_date is None:
        # 未做日初：返空 list，code=0（不是错误，是未初始化状态）
        return {"code": 0, "msg": "no active trading day", "list": []}

    return {
        "code": 0,
        "msg": "",
        "list": [{"trd_date": trd_date, "status": "active"}],
    }
