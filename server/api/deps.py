"""
deps.py — FastAPI 依赖注入共享 helper

RPC 健康集中校验:
- 调 qry_* / place / cancel 等 RPC 的端点必须 Depends(require_rpc_ok)
- qry_asset 不加 (它本身是 rpc_health 心跳探测, 加了会自检死锁)
- 失败 → 503 + 统一文案直接返回前端, 不继续
"""
from fastapi import HTTPException

from server.services.rpc_health import check_ok


# 统一文案, 与前端 handled 的 RPC_COMM_ERROR 错误码对齐
_RPC_ERR_DETAIL = {"code": "RPC_COMM_ERROR", "msg": "RPC 通信异常，操作无法完成"}


def require_rpc_ok() -> None:
    """FastAPI 依赖: 调用 broker RPC 的端点必须依赖此检查.

    设计要点:
    - 只校验 rpc_health.check_ok(), 不调实际 RPC (避免加重 broker)
    - 失败直接 raise HTTPException(503, "RPC_COMM_ERROR") — 前端按 code 判显示
    - 心跳探测路径 (rpc_health._sync_loop) **不**依赖此函数, 否则自检死锁

    用法:
        @router.post("/api/orders/place")
        async def place_order(req: OrderReq, _: None = Depends(require_rpc_ok)):
            ...
    """
    if not check_ok():
        raise HTTPException(status_code=503, detail=_RPC_ERR_DETAIL)
