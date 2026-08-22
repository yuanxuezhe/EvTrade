"""
query.py — GET /api/orders 和 GET /api/orders/history 委托查询端点

行为：
- 纯 DB 读路径，不调 RPC
- GET /            : 委托列表，按 trd_date 默认 = 激活日
- GET /history     : 任意交易日历史（admin 也用）

- 单字段查询走 Orders.query_by('x', v)
- 复合条件 (start_date/end_date + stock_code + status) → Orders.query_all() + 内存过滤
  (数据量小, 区间 API 不支持, 走全表 + Python 过滤)
- count 走 aggregate('orders', 'COUNT', '*', where=..., params=...)
- 排序 + 分页 → 内存排序 + 切片
"""
from typing import Optional

from fastapi import Depends, Query

from server.auth.deps import get_current_user
from server.models.user import User
from server.repo.orders import _get_active_trd_date  # tables-backed helper
from server.api.orders.schemas import ListOrdersResponse, _to_order_out
from server.tables import Orders
from server.tables.base import aggregate


def _filter_orders(rows, trd_date=None, start_date=None, end_date=None,
                   stock_code=None, status=None):
    """复合过滤 + 排序 + 切片 helper (内存过滤模式)

    Args:
        rows: List[Row] (Orders.query_all() 默认按 (trd_date, order_no) 升序)
        trd_date / start_date / end_date: 三选一/可空, 业务见 list_orders
        stock_code / status: 单一字段等值过滤 (None 跳过)

    Returns:
        (filtered_total, sorted_desc_rows)

    无 task_id 入参 (前端纯缓存筛选, 后端不接 task_id 参数)
    """
    # 区间 / 单日过滤 (按用户伪代码语义: 区间优先于 trd_date)
    if start_date or end_date:
        def in_range(r):
            td = r.trd_date or ""
            if start_date and td < start_date:
                return False
            if end_date and td > end_date:
                return False
            return True
        rows = [r for r in rows if in_range(r)]
    elif trd_date:
        rows = [r for r in rows if r.trd_date == trd_date]

    if stock_code:
        rows = [r for r in rows if r.stock_code == stock_code]
    if status:
        rows = [r for r in rows if r.status == status]

    # 倒序按 order_time (按用户原行为: desc(Order.order_time))
    rows = sorted(rows, key=lambda r: (r.order_time or ""), reverse=True)
    return rows


def register_query(router):
    """注册 GET / 和 GET /history 端点到 FastAPI router。"""

    @router.get("", response_model=ListOrdersResponse)
    async def list_orders(
        stock_code: Optional[str] = None,
        status: Optional[str] = None,
        all: Optional[bool] = Query(False, description="返全部 orders 不限日期（前端 startup 缓存）"),
        trd_date: Optional[str] = Query(None, description="8 位数字 YYYYMMDD，缺省 = 激活日"),
        start_date: Optional[str] = Query(
            None, regex=r"^\d{8}$",
            description="起始交易日 YYYYMMDD（含）",
        ),
        end_date: Optional[str] = Query(
            None, regex=r"^\d{8}$",
            description="结束交易日 YYYYMMDD（含）",
        ),
        limit: int = Query(2000, le=10000),  # 默认 2k (前端 startup 缓存 / 跨日管理)
        offset: int = 0,
        user: User = Depends(get_current_user),
    ):
        """委托列表（纯 DB）

        过滤语义：
        - all=true → 跳日期过滤返所有 (前端 startup 一次性缓存)
        - start_date/end_date 任一存在 → 走区间模式（start_date <= trd_date <= end_date）
        - 都不存在 → 走缺省模式（trd_date = 激活日，向后兼容）
        - 区间模式优先级高于 trd_date：start_date/end_date 存在时 trd_date 被忽略

        注: task_id 过滤由前端纯缓存层做 (不消耗后端), 避免 API 膨胀

        走 Orders.query_all() + 内存过滤
        """
        # 缺省模式：trd_date 显式给则用，否则激活日 (SysStatus 单行 id=1)
        # all=true 跳过 trd_date 默认
        if all is False and not (start_date or end_date) and not trd_date:
            trd_date = _get_active_trd_date()

        # Orders.query_all() 按 (trd_date, order_no) 升序全表 → 内存过滤
        all_rows = Orders.query_all()
        filtered = _filter_orders(
            all_rows,
            trd_date=None if all else trd_date,  # all=true 不过滤 trd_date
            start_date=start_date,
            end_date=end_date,
            stock_code=stock_code,
            status=status,
        )
        # all=true 时放宽 limit 上限到 1w
        effective_limit = min(limit, 10000) if all else min(limit, 500)
        total = len(filtered)
        # offset / limit 切片
        paged = filtered[offset: offset + effective_limit]

        return ListOrdersResponse(
            code=0, msg="", total=total,
            list=[_to_order_out(r) for r in paged],
        )

    @router.get("/history", response_model=ListOrdersResponse)
    async def orders_history(
        trd_date: str = Query(..., description="8 位数字 YYYYMMDD"),
        stock_code: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = Query(500, le=2000),
        user: User = Depends(get_current_user),
    ):
        """任意交易日历史委托（admin 也用）

        走 Orders.query_all() + 内存过滤
        """
        all_rows = Orders.query_all()
        filtered = _filter_orders(
            all_rows,
            trd_date=trd_date,
            stock_code=stock_code,
            status=status,
        )
        # 注意: history 端点不返 total (保持向后兼容)
        paged = filtered[:limit]
        return ListOrdersResponse(
            code=0, msg="", total=len(filtered),
            list=[_to_order_out(r) for r in paged],
        )
