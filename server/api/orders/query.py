"""
query.py — GET /api/orders 和 GET /api/orders/history 委托查询端点

行为：
- 纯 DB 读路径，不调 RPC
- GET /            : 委托列表，按 trd_date 默认 = 激活日
- GET /history     : 任意交易日历史（admin 也用）
"""
from typing import Optional

from fastapi import Depends, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session

from server.auth.deps import get_current_user
from server.db import get_db
from server.models.orm import Order, SysStatus, get_active_trd_date
from server.models.user import User
from server.api.orders.schemas import ListOrdersResponse, _to_order_out


def register_query(router):
    """注册 GET / 和 GET /history 端点到 FastAPI router。"""

    @router.get("", response_model=ListOrdersResponse)
    async def list_orders(
        stock_code: Optional[str] = None,
        status: Optional[str] = None,
        trd_date: Optional[str] = Query(None, description="8 位数字 YYYYMMDD，缺省 = 激活日"),
        start_date: Optional[str] = Query(
            None, regex=r"^\d{8}$",
            description="起始交易日 YYYYMMDD（含）",
        ),
        end_date: Optional[str] = Query(
            None, regex=r"^\d{8}$",
            description="结束交易日 YYYYMMDD（含）",
        ),
        limit: int = Query(100, le=500),
        offset: int = 0,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        """委托列表（纯 DB）

        过滤语义：
        - start_date/end_date 任一存在 → 走区间模式（start_date <= trd_date <= end_date）
        - 都不存在 → 走缺省模式（trd_date = 激活日，向后兼容）
        - 区间模式优先级高于 trd_date：start_date/end_date 存在时 trd_date 被忽略
        """
        q = db.query(Order)

        if start_date or end_date:
            # 区间模式（4 种子情况：仅 start / 仅 end / 都给 / 都给且反向 → 都靠 SQLAlchemy 自然处理）
            if start_date:
                q = q.filter(Order.trd_date >= start_date)
            if end_date:
                q = q.filter(Order.trd_date <= end_date)
        else:
            # 缺省模式：trd_date 显式给则用，否则激活日 (v_next: SysStatus 单行 id=1)
            if not trd_date:
                trd_date = get_active_trd_date(db)
            if trd_date:
                q = q.filter(Order.trd_date == trd_date)

        if stock_code:
            q = q.filter(Order.stock_code == stock_code)
        if status:
            q = q.filter(Order.status == status)
        total = q.count()
        rows = q.order_by(desc(Order.order_time)).offset(offset).limit(limit).all()

        return ListOrdersResponse(
            code=0, msg="", total=total,
            list=[_to_order_out(r) for r in rows],
        )

    @router.get("/history", response_model=ListOrdersResponse)
    async def orders_history(
        trd_date: str = Query(..., description="8 位数字 YYYYMMDD"),
        stock_code: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = Query(500, le=2000),
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        """任意交易日历史委托（admin 也用）"""
        q = db.query(Order).filter(Order.trd_date == trd_date)
        if stock_code:
            q = q.filter(Order.stock_code == stock_code)
        if status:
            q = q.filter(Order.status == status)
        total = q.count()
        rows = q.order_by(desc(Order.order_time)).limit(limit).all()
        return ListOrdersResponse(
            code=0, msg="", total=total,
            list=[_to_order_out(r) for r in rows],
        )
